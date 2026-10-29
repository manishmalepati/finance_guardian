from datetime import date, datetime, timezone
from types import SimpleNamespace

from backend.db.models import CategorizationCorrection, Transaction
from backend.intelligence.categorization import LabeledExample, clean_text
from backend.services.categorization import CategorizationService
from evals.categorization_experiment import evaluate, split_examples, synthetic_examples


def test_text_features_remove_numeric_reference_without_using_label():
    assert clean_text("PINE Market purchase ref 12345") == "pine market purchase ref"


def test_chronological_and_merchant_held_out_splits_do_not_leak():
    splits = split_examples(synthetic_examples())
    train, validation, test = splits["chronological"]
    assert max(item.posted_date for item in train) < min(item.posted_date for item in validation)
    assert max(item.posted_date for item in validation) < min(item.posted_date for item in test)
    group_train, _, group_test = splits["merchant_held_out"]
    assert {item.merchant for item in group_train}.isdisjoint({item.merchant for item in group_test})
    assert max(item.posted_date for item in group_train) < min(item.posted_date for item in group_test)


def test_offline_experiment_and_small_label_abstention():
    result = evaluate()
    assert result["deployment_decision"].startswith("offline_only")
    assert result["splits"]["chronological"]["tfidf_logistic_regression"]["count"] == 24
    assert result["splits"]["merchant_held_out"]["alias_baseline"]["coverage"] == 0
    example = LabeledExample("one", date(2026, 1, 1), datetime(2026, 1, 2, tzinfo=timezone.utc),
                             "Synthetic purchase", "Synthetic", "food_groceries", "user_explicit")
    assert evaluate([example])["status"] == "insufficient_independent_labels"


def test_explicit_user_choice_creates_one_independent_label(monkeypatch):
    class SessionStub:
        def __init__(self):
            self.added = []
            self.commits = 0

        def get(self, model, identifier):
            assert model is Transaction
            return SimpleNamespace(id=identifier, description="Synthetic Market")

        def add(self, item):
            self.added.append(item)

        def commit(self):
            self.commits += 1

    session = SessionStub()
    service = CategorizationService(session)
    monkeypatch.setattr(service, "_require_category", lambda category_id: None)
    monkeypatch.setattr(service, "_upsert_alias", lambda **kwargs: None)
    monkeypatch.setattr(service, "_apply_alias_to_matching_transactions", lambda normalized: 100)
    result = service.set_transaction_category("synthetic-id", "food_groceries")
    assert result["matching_transactions_updated"] == 100
    corrections = [item for item in session.added if isinstance(item, CategorizationCorrection)]
    assert len(corrections) == 1
    assert corrections[0].transaction_id == "synthetic-id"
    assert corrections[0].source == "user_explicit"
    assert session.commits == 1
