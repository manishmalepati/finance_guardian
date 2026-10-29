"""Offline, provenance-aware categorization comparison with no external calls."""

import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

from backend.intelligence.categorization import MODEL_VERSION, LabeledExample, feature_text
from backend.services.categorization import SEED_ALIASES, MerchantNormalizer


SEED = 2718
CATEGORIES = {
    "food_groceries": (("Pine Market", "market groceries produce"),
                       ("River Foods", "supermarket pantry groceries"),
                       ("Oak Pantry", "fresh produce store")),
    "food_prepared": (("Blue Cafe", "restaurant lunch takeaway"),
                      ("Sunny Kitchen", "dinner restaurant takeout"),
                      ("Corner Deli", "sandwich cafe lunch")),
    "transport_fuel": (("Hill Fuel", "gas station fuel pump"),
                       ("Cedar Gas", "petrol station pump"),
                       ("North Energy", "fuel forecourt refill")),
    "housing_utilities": (("City Water", "water utility bill"),
                          ("Valley Electric", "electric power utility"),
                          ("Lake Power", "energy utility monthly bill")),
}


def synthetic_examples() -> list[LabeledExample]:
    """Independent fixture definitions; hints deliberately contain deterministic errors."""
    examples = []
    labels = list(CATEGORIES)
    for month_index in range(12):
        year = 2025 + month_index // 12
        month = month_index % 12 + 1
        for category, merchants in CATEGORIES.items():
            for merchant_index, (merchant, context) in enumerate(merchants):
                posted = date(year, month, 3 + merchant_index * 6)
                hint = labels[(labels.index(category) + 1) % len(labels)] if (month_index + merchant_index) % 6 == 0 else category
                examples.append(LabeledExample(
                    transaction_id=f"synthetic-{month_index}-{category}-{merchant_index}",
                    posted_date=posted,
                    label_available_at=datetime.combine(posted + timedelta(days=1), datetime.min.time(), timezone.utc),
                    description=f"{context} purchase ref {1000 + month_index * 10 + merchant_index}",
                    merchant=merchant, category_id=category,
                    label_source="synthetic_independent", plaid_hint=hint))
    return examples


def split_examples(examples: list[LabeledExample]) -> dict[str, tuple[list[LabeledExample], list[LabeledExample], list[LabeledExample]]]:
    ordered = sorted(examples, key=lambda item: (item.label_available_at, item.transaction_id))
    if not ordered:
        return {}
    # Explicit calendar cutoffs make the synthetic split reproducible and auditable.
    if all(item.label_source == "synthetic_independent" for item in ordered):
        train = [item for item in ordered if item.posted_date < date(2025, 9, 1)]
        validation = [item for item in ordered if date(2025, 9, 1) <= item.posted_date < date(2025, 11, 1)]
        test = [item for item in ordered if item.posted_date >= date(2025, 11, 1)]
    else:
        cut1 = ordered[int(len(ordered) * 0.65)].label_available_at
        cut2 = ordered[int(len(ordered) * 0.8)].label_available_at
        train = [item for item in ordered if item.label_available_at < cut1]
        validation = [item for item in ordered if cut1 <= item.label_available_at < cut2]
        test = [item for item in ordered if item.label_available_at >= cut2]
    heldout_merchants = {merchant.casefold() for merchants in CATEGORIES.values() for merchant, _ in merchants[-1:]}
    if any(item.label_source != "synthetic_independent" for item in ordered):
        # Select one merchant per category, with no test merchant in training.
        from hashlib import sha256
        by_category = {}
        for item in ordered:
            by_category.setdefault(item.category_id, set()).add(item.merchant.casefold())
        heldout_merchants = {sorted(merchants, key=lambda value: sha256(value.encode()).hexdigest())[0]
                             for merchants in by_category.values() if len(merchants) >= 2}
    group_train = [item for item in train if item.merchant.casefold() not in heldout_merchants]
    group_val = [item for item in validation if item.merchant.casefold() not in heldout_merchants]
    group_test = [item for item in test if item.merchant.casefold() in heldout_merchants]
    return {"chronological": (train, validation, test),
            "merchant_held_out": (group_train, group_val, group_test)}


def _metrics(y_true, y_pred, proba, classes, elapsed_ms: float, threshold: float | None) -> dict:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
    import numpy as np

    labels = sorted(set(y_true) | set(y_pred))
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0)
    per_category = {label: {"precision": round(float(p), 3), "recall": round(float(r), 3),
                            "f1": round(float(f), 3), "support": int(s)}
                    for label, p, r, f, s in zip(labels, precision, recall, f1, support)}
    output = {"count": len(y_true), "accuracy": round(float(accuracy_score(y_true, y_pred)), 3),
              "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 3),
              "per_category": per_category, "confusion_labels": labels,
              "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
              "inference_ms": round(elapsed_ms, 2)}
    if proba is not None:
        top3 = [set(classes[index] for index in np.argsort(row)[-3:]) for row in proba]
        output["top_3_accuracy"] = round(sum(label in choices for label, choices in zip(y_true, top3)) / len(y_true), 3)
        scores = proba.max(axis=1)
        correct = np.array([truth == predicted for truth, predicted in zip(y_true, y_pred)])
        bins = [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.000001)]
        output["expected_calibration_error"] = round(sum(
            abs(float(scores[(scores >= low) & (scores < high)].mean()) -
                float(correct[(scores >= low) & (scores < high)].mean())) *
            int(((scores >= low) & (scores < high)).sum()) / len(scores)
            for low, high in bins if ((scores >= low) & (scores < high)).any()), 3)
        if threshold is not None:
            accepted = scores >= threshold
            output["auto_accept_threshold_from_validation"] = threshold
            output["auto_accept_coverage"] = round(float(accepted.mean()), 3)
            output["auto_accept_precision"] = round(float(correct[accepted].mean()), 3) if accepted.any() else None
    return output


def _select_threshold(model, validation: list[LabeledExample]) -> float | None:
    if not validation:
        return None
    probabilities = model.predict_proba([feature_text(item) for item in validation])
    predictions = model.classes_[probabilities.argmax(axis=1)]
    scores = probabilities.max(axis=1)
    for threshold in (.5, .6, .7, .8, .9, .95):
        accepted = scores >= threshold
        if accepted.any():
            truths = [item.category_id for item, keep in zip(validation, accepted) if keep]
            guesses = [prediction for prediction, keep in zip(predictions, accepted) if keep]
            if sum(a == b for a, b in zip(truths, guesses)) / len(truths) >= .95:
                return threshold
    return None


def _evaluate_split(train, validation, test, *, embedding_model_path: str | None = None) -> tuple[dict, object | None]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    if len(set(item.category_id for item in train)) < 2 or not test:
        return {"status": "insufficient_split_data", "train_count": len(train), "test_count": len(test)}, None
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True),
                          LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED))
    model.fit([feature_text(item) for item in train], [item.category_id for item in train])
    threshold = _select_threshold(model, validation)
    features = [feature_text(item) for item in test]
    started = perf_counter()
    predictions = model.predict(features)
    probabilities = model.predict_proba(features)
    elapsed_ms = (perf_counter() - started) * 1000
    truth = [item.category_id for item in test]
    result = {"train_count": len(train), "validation_count": len(validation), "test_count": len(test),
              "tfidf_logistic_regression": _metrics(truth, predictions, probabilities,
                                                    model.classes_, elapsed_ms, threshold)}
    aliases = {item.merchant.casefold(): item.category_id for item in train}
    alias_known = [item for item in test if item.merchant.casefold() in aliases]
    result["alias_baseline"] = {"coverage": round(len(alias_known) / len(test), 3),
                                "accuracy_on_covered": round(sum(aliases[item.merchant.casefold()] == item.category_id
                                                                 for item in alias_known) / len(alias_known), 3) if alias_known else None}
    normalizer = MerchantNormalizer()
    seed_predictions = []
    for item in test:
        normalized = normalizer.normalize(item.description)
        matches = [(pattern, category) for pattern, _, category in SEED_ALIASES
                   if pattern == normalized or f" {pattern} " in f" {normalized} "]
        if matches:
            seed_predictions.append((item, max(matches, key=lambda match: len(match[0]))[1]))
    result["seeded_rule_baseline"] = {"coverage": round(len(seed_predictions) / len(test), 3),
                                      "accuracy_on_covered": round(sum(item.category_id == prediction for item, prediction in seed_predictions) / len(seed_predictions), 3) if seed_predictions else None}
    hinted = [item for item in test if item.plaid_hint]
    result["plaid_hint_baseline"] = {"coverage": round(len(hinted) / len(test), 3),
                                     "accuracy_on_covered": round(sum(item.plaid_hint == item.category_id
                                                                      for item in hinted) / len(hinted), 3) if hinted else None,
                                     "note": "Synthetic hints are generated fixture values, not measured Plaid performance."}
    if embedding_model_path:
        path = Path(embedding_model_path).resolve()
        if not path.is_dir():
            raise ValueError("Embedding model must be an existing local directory.")
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(str(path))
        classifier = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED)
        classifier.fit(encoder.encode([feature_text(item) for item in train]),
                       [item.category_id for item in train])
        started = perf_counter()
        embedding_features = encoder.encode(features)
        embedding_predictions = classifier.predict(embedding_features)
        embedding_probabilities = classifier.predict_proba(embedding_features)
        result["local_embedding_logistic_regression"] = _metrics(
            truth, embedding_predictions, embedding_probabilities, classifier.classes_,
            (perf_counter() - started) * 1000, None)
    else:
        result["local_embedding_logistic_regression"] = {"status": "skipped_no_local_model"}
    result["errors"] = [{**({"id": item.transaction_id} if item.label_source == "synthetic_independent" else {}),
                         "actual": item.category_id, "predicted": str(prediction)}
                        for item, prediction in zip(test, predictions) if item.category_id != prediction][:12]
    return result, model


def evaluate(examples: list[LabeledExample] | None = None, *, embedding_model_path: str | None = None,
             save_artifact: bool = False) -> dict:
    from sklearn import __version__ as sklearn_version

    examples = synthetic_examples() if examples is None else examples
    provenance = dict(Counter(item.label_source for item in examples))
    independent = [item for item in examples if item.label_source in ("synthetic_independent", "user_explicit")]
    class_counts = Counter(item.category_id for item in independent)
    merchant_counts = {category: len({item.merchant.casefold() for item in independent
                                      if item.category_id == category}) for category in class_counts}
    if len(independent) < 60 or len(class_counts) < 3 or min(class_counts.values(), default=0) < 10 \
            or min(merchant_counts.values(), default=0) < 2:
        return {"status": "insufficient_independent_labels", "independent_count": len(independent),
                "provenance_counts": provenance, "class_counts": dict(class_counts),
                "merchant_counts": merchant_counts, "deployment_decision": "offline_only"}
    splits = split_examples(independent)
    results = {}
    artifact_model = None
    for name, (train, validation, test) in splits.items():
        results[name], model = _evaluate_split(train, validation, test,
                                               embedding_model_path=embedding_model_path)
        if name == "chronological":
            artifact_model = model
    output = {"dataset": "synthetic_categorization_v1" if examples[0].label_source == "synthetic_independent" else "local_explicit_corrections",
              "seed": SEED, "model_version": MODEL_VERSION, "scikit_learn_version": sklearn_version,
              "provenance_counts": provenance, "splits": results,
              "deployment_decision": "offline_only_until_independent_real_holdout_validates_precision_and_calibration"}
    if save_artifact and artifact_model is not None:
        import joblib
        directory = Path(__file__).resolve().parents[1] / ".local" / "models"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{MODEL_VERSION}.joblib"
        joblib.dump(artifact_model, path)
        (directory / f"{MODEL_VERSION}.json").write_text(json.dumps({
            "model_version": MODEL_VERSION, "dataset": output["dataset"],
            "scikit_learn_version": sklearn_version, "provenance_counts": provenance,
            "deployment_decision": output["deployment_decision"]}, indent=2), encoding="utf-8")
        output["artifact_path"] = str(path)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("synthetic", "local"), default="synthetic")
    parser.add_argument("--embedding-model-path", default=None)
    parser.add_argument("--save-artifact", action="store_true")
    args = parser.parse_args()
    data = None
    if args.source == "local":
        from sqlalchemy.orm import Session
        from backend.db.session import engine
        from backend.intelligence.categorization import explicit_local_examples
        with Session(engine) as session:
            data = explicit_local_examples(session)
    print(json.dumps(evaluate(data, embedding_model_path=args.embedding_model_path,
                              save_artifact=args.save_artifact), indent=2))
