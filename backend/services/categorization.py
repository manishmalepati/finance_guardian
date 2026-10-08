from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.common.exceptions import AgentExecutionError, ConfigurationError
from backend.core.config import settings
from backend.db.models import (
    CategorizationJob,
    CategoryTaxonomy,
    MerchantAlias,
    RawTransaction,
    TransactionCategorization,
)
from backend.llm.base import LLMProvider
from backend.llm.providers import LLMProviderFactory

logger = logging.getLogger(__name__)


CATEGORY_TAXONOMY = [
    {
        "category_id": "income",
        "display_name": "Income",
        "subcategories": [
            ("income_salary", "Salary"),
            ("income_interest_dividends", "Interest & Dividends"),
            ("income_refunds_reimbursements", "Refunds & Reimbursements"),
            ("income_other", "Other Income"),
        ],
    },
    {
        "category_id": "food_dining",
        "display_name": "Food & Dining",
        "subcategories": [
            ("food_groceries", "Groceries"),
            ("food_prepared", "Restaurants & Prepared Food"),
            ("food_bars_alcohol", "Bars & Alcohol"),
        ],
    },
    {
        "category_id": "housing",
        "display_name": "Housing",
        "subcategories": [
            ("housing_rent_mortgage", "Rent & Mortgage"),
            ("housing_utilities", "Utilities"),
            ("housing_internet_phone", "Internet & Phone"),
            ("housing_maintenance", "Home Maintenance"),
            ("housing_supplies", "Home Supplies"),
        ],
    },
    {
        "category_id": "transportation",
        "display_name": "Transportation",
        "subcategories": [
            ("transport_fuel", "Fuel"),
            ("transport_rideshare_taxi", "Rideshare & Taxi"),
            ("transport_public_transit", "Public Transit"),
            ("transport_parking_tolls", "Parking & Tolls"),
            ("transport_vehicle_maintenance", "Vehicle Maintenance"),
            ("transport_vehicle_insurance", "Vehicle Insurance"),
        ],
    },
    {
        "category_id": "shopping",
        "display_name": "Shopping",
        "subcategories": [
            ("shopping_general", "General Merchandise"),
            ("shopping_clothing", "Clothing"),
            ("shopping_electronics", "Electronics"),
            ("shopping_personal_care", "Personal Care"),
            ("shopping_home_goods", "Home Goods"),
        ],
    },
    {
        "category_id": "health",
        "display_name": "Health",
        "subcategories": [
            ("health_medical", "Medical"),
            ("health_pharmacy", "Pharmacy"),
            ("health_dental_vision", "Dental & Vision"),
            ("health_fitness", "Fitness"),
        ],
    },
    {
        "category_id": "entertainment",
        "display_name": "Entertainment",
        "subcategories": [
            ("entertainment_events", "Events & Venues"),
            ("entertainment_digital", "Digital Entertainment"),
            ("entertainment_hobbies", "Hobbies"),
        ],
    },
    {
        "category_id": "subscriptions",
        "display_name": "Subscriptions",
        "subcategories": [
            ("subscriptions_streaming", "Streaming"),
            ("subscriptions_software", "Software"),
            ("subscriptions_memberships", "Memberships"),
        ],
    },
    {
        "category_id": "travel",
        "display_name": "Travel",
        "subcategories": [
            ("travel_flights", "Flights"),
            ("travel_lodging", "Lodging"),
            ("travel_rental_cars", "Rental Cars"),
            ("travel_ground_transport", "Ground Transportation"),
            ("travel_activities", "Travel Activities"),
        ],
    },
    {
        "category_id": "financial",
        "display_name": "Financial",
        "subcategories": [
            ("financial_credit_card_payment", "Credit Card Payments"),
            ("financial_transfers", "Transfers"),
            ("financial_fees_interest", "Fees & Interest"),
            ("financial_cash_atm", "Cash & ATM"),
            ("financial_taxes", "Taxes"),
        ],
    },
    {
        "category_id": "education",
        "display_name": "Education",
        "subcategories": [
            ("education_tuition", "Tuition"),
            ("education_courses", "Courses"),
            ("education_books_supplies", "Books & Supplies"),
        ],
    },
    {
        "category_id": "gifts_donations",
        "display_name": "Gifts & Donations",
        "subcategories": [
            ("gifts_donations_gifts", "Gifts"),
            ("gifts_donations_charity", "Charity"),
        ],
    },
    {
        "category_id": "other",
        "display_name": "Other",
        "subcategories": [
            ("other_uncategorized", "Uncategorized"),
            ("other_misc", "Other"),
        ],
    },
]


SEED_ALIASES = [
    ("uber eats", "Uber Eats", "food_prepared"),
    ("doordash", "DoorDash", "food_prepared"),
    ("uber trip", "Uber", "transport_rideshare_taxi"),
    ("lyft", "Lyft", "transport_rideshare_taxi"),
    ("wal mart", "Walmart", "shopping_general"),
    ("walmart", "Walmart", "shopping_general"),
    ("regal cinemas", "Regal Cinemas", "entertainment_events"),
    ("payment thank you", "Credit Card Payment", "financial_credit_card_payment"),
]


@dataclass(frozen=True)
class CategorizationResult:
    category_id: str
    canonical_merchant_name: str
    source: str
    confidence: Decimal


class MerchantNormalizer:
    """Normalize noisy statement descriptions into stable matching text."""

    _noise_tokens = {
        "www",
        "com",
        "help",
        "order",
        "inc",
        "llc",
        "co",
        "ca",
        "ny",
        "tx",
        "tn",
        "de",
        "us",
    }

    def normalize(self, description: str) -> str:
        value = description.lower()
        value = value.replace("&", " and ")
        value = re.sub(r"[^a-z0-9]+", " ", value)
        tokens = [token for token in value.split() if not token.isdigit() and token not in self._noise_tokens]
        return " ".join(tokens)


class CategorizationService:
    """Categorize raw transactions through taxonomy, aliases, user edits, and LLM suggestions."""

    def __init__(self, session: Session, llm_provider: LLMProvider | None = None):
        self.session = session
        self.normalizer = MerchantNormalizer()
        self.llm_provider = llm_provider

    def seed_defaults(self) -> None:
        default_category_ids = {
            parent["category_id"]
            for parent in CATEGORY_TAXONOMY
        } | {
            category_id
            for parent in CATEGORY_TAXONOMY
            for category_id, _ in parent["subcategories"]
        }
        existing_categories = {
            category.category_id: category
            for category in self.session.scalars(select(CategoryTaxonomy)).all()
        }
        for category in existing_categories.values():
            if category.category_id not in default_category_ids:
                category.is_active = False

        sort_order = 1
        for parent_index, parent in enumerate(CATEGORY_TAXONOMY, start=1):
            parent_id = parent["category_id"]
            existing_parent = existing_categories.get(parent_id)
            if existing_parent:
                existing_parent.parent_category_id = None
                existing_parent.display_name = parent["display_name"]
                existing_parent.level = 1
                existing_parent.sort_order = sort_order
                existing_parent.is_active = True
            else:
                self.session.add(
                    CategoryTaxonomy(
                        category_id=parent_id,
                        parent_category_id=None,
                        display_name=parent["display_name"],
                        level=1,
                        sort_order=sort_order,
                    )
                )
            sort_order += 1
            for child_index, (category_id, display_name) in enumerate(parent["subcategories"], start=1):
                existing_child = existing_categories.get(category_id)
                if existing_child:
                    existing_child.parent_category_id = parent_id
                    existing_child.display_name = display_name
                    existing_child.level = 2
                    existing_child.sort_order = parent_index * 100 + child_index
                    existing_child.is_active = True
                else:
                    self.session.add(
                        CategoryTaxonomy(
                            category_id=category_id,
                            parent_category_id=parent_id,
                            display_name=display_name,
                            level=2,
                            sort_order=parent_index * 100 + child_index,
                        )
                    )

        existing_aliases = {
            alias.normalized_pattern: alias
            for alias in self.session.scalars(select(MerchantAlias)).all()
        }
        for pattern, merchant_name, category_id in SEED_ALIASES:
            normalized_pattern = self.normalizer.normalize(pattern)
            existing_alias = existing_aliases.get(normalized_pattern)
            if existing_alias:
                existing_alias.canonical_merchant_name = merchant_name
                existing_alias.category_id = category_id
                existing_alias.source = "seed"
                existing_alias.confidence = Decimal("1.000")
                existing_alias.status = "active"
            else:
                self.session.add(
                    MerchantAlias(
                        normalized_pattern=normalized_pattern,
                        canonical_merchant_name=merchant_name,
                        category_id=category_id,
                        source="seed",
                        confidence=Decimal("1.000"),
                    )
                )
        self.session.commit()

    def list_categories(self) -> list[dict]:
        rows = self.session.scalars(
            select(CategoryTaxonomy)
            .where(CategoryTaxonomy.is_active.is_(True))
            .order_by(CategoryTaxonomy.sort_order)
        ).all()
        children_by_parent: dict[str, list[CategoryTaxonomy]] = defaultdict(list)
        parents = []
        for row in rows:
            if row.parent_category_id:
                children_by_parent[row.parent_category_id].append(row)
            else:
                parents.append(row)
        return [
            {
                "category_id": parent.category_id,
                "display_name": parent.display_name,
                "subcategories": [
                    {
                        "category_id": child.category_id,
                        "display_name": child.display_name,
                    }
                    for child in children_by_parent[parent.category_id]
                ],
            }
            for parent in parents
        ]

    def summary(self) -> dict:
        total_transactions = self.session.scalar(select(func.count()).select_from(RawTransaction)) or 0
        categorized_transactions = (
            self.session.scalar(
                select(func.count(func.distinct(TransactionCategorization.transaction_id))).where(
                    TransactionCategorization.status == "active"
                )
            )
            or 0
        )
        job_counts = dict(
            self.session.execute(
                select(CategorizationJob.status, func.count())
                .group_by(CategorizationJob.status)
                .order_by(CategorizationJob.status)
            ).all()
        )
        return {
            "total_transactions": total_transactions,
            "categorized_transactions": categorized_transactions,
            "uncategorized_transactions": total_transactions - categorized_transactions,
            "jobs": job_counts,
        }

    def list_jobs(self, limit: int = 100, status: str | None = None) -> list[dict]:
        status_rank = case(
            (CategorizationJob.status == "pending", 0),
            (CategorizationJob.status == "failed", 1),
            (CategorizationJob.status == "needs_review", 2),
            else_=3,
        )
        statement = select(CategorizationJob).order_by(status_rank, CategorizationJob.updated_at.desc()).limit(limit)
        if status:
            statement = statement.where(CategorizationJob.status == status)
        rows = self.session.scalars(
            statement
        ).all()
        return [
            {
                "id": row.id,
                "normalized_merchant": row.normalized_merchant,
                "example_descriptions": json.loads(row.example_descriptions),
                "transaction_count": row.transaction_count,
                "status": row.status,
                "error_message": row.error_message,
            }
            for row in rows
        ]

    def apply_known_aliases_and_queue_unknowns(self, commit: bool = True) -> dict:
        transactions = self._transactions_without_active_category()
        aliases = self._active_aliases()
        categorized = 0
        unknowns: dict[str, list[RawTransaction]] = defaultdict(list)

        for transaction in transactions:
            normalized = self.normalizer.normalize(transaction.description)
            alias = self._match_alias(normalized, aliases)
            if alias:
                self._set_transaction_category(
                    transaction=transaction,
                    result=CategorizationResult(
                        category_id=alias.category_id,
                        canonical_merchant_name=alias.canonical_merchant_name,
                        source=alias.source,
                        confidence=alias.confidence,
                    ),
                    normalized_merchant=normalized,
                )
                categorized += 1
            else:
                unknowns[normalized].append(transaction)

        queued = self._upsert_jobs(unknowns)
        if commit:
            self.session.commit()
        return {
            "transactions_scanned": len(transactions),
            "transactions_categorized": categorized,
            "unknown_merchants_queued": queued,
        }

    def categorize_with_llm(self, limit: int = 20) -> dict:
        if self.llm_provider is None:
            settings.require_agent_configuration()
            self.llm_provider = LLMProviderFactory(settings).build(max_tokens=2000)

        jobs = self.session.scalars(
            select(CategorizationJob)
            .where(CategorizationJob.status.in_(["pending", "failed"]))
            .order_by(CategorizationJob.created_at)
            .limit(limit)
        ).all()
        if not jobs:
            return {"jobs_processed": 0, "aliases_created": 0, "transactions_categorized": 0}

        categories = self.list_categories()
        results = self._llm_categorize_jobs(jobs=jobs, categories=categories)
        valid_categories = {
            subcategory["category_id"]
            for category in categories
            for subcategory in category["subcategories"]
        }
        aliases_created = 0

        for job in jobs:
            result = results.get(job.normalized_merchant)
            if result is None:
                job.status = "failed"
                job.error_message = "LLM did not return a categorization for this merchant."
                continue
            if result["category_id"] not in valid_categories:
                job.status = "failed"
                job.error_message = f"Unknown category_id returned by LLM: {result['category_id']}"
                continue

            confidence = Decimal(str(result.get("confidence", 0))).quantize(Decimal("0.001"))
            status = "active" if confidence >= Decimal("0.850") else "pending_review"
            alias = self._upsert_alias(
                normalized_pattern=job.normalized_merchant,
                canonical_merchant_name=result["canonical_merchant_name"],
                category_id=result["category_id"],
                source="llm",
                confidence=confidence,
                status=status,
            )
            aliases_created += int(alias is not None)
            job.status = "complete" if status == "active" else "needs_review"
            job.error_message = None if status == "active" else "LLM confidence is below auto-accept threshold."

        self.session.commit()
        apply_result = self.apply_known_aliases_and_queue_unknowns()
        return {
            "jobs_processed": len(jobs),
            "aliases_created": aliases_created,
            "transactions_categorized": apply_result["transactions_categorized"],
        }

    def set_transaction_category(
        self,
        transaction_id: str,
        category_id: str,
        canonical_merchant_name: str | None = None,
        apply_to_matching_merchant: bool = True,
    ) -> dict:
        self._require_category(category_id)
        transaction = self.session.get(RawTransaction, transaction_id)
        if transaction is None:
            raise ValueError("Transaction was not found.")

        normalized = self.normalizer.normalize(transaction.description)
        merchant_name = canonical_merchant_name or self._title_from_normalized(normalized)
        if apply_to_matching_merchant:
            self._upsert_alias(
                normalized_pattern=normalized,
                canonical_merchant_name=merchant_name,
                category_id=category_id,
                source="user",
                confidence=Decimal("1.000"),
                status="active",
            )
            matching_transactions_updated = self._apply_alias_to_matching_transactions(normalized)
        else:
            self._set_transaction_category(
                transaction=transaction,
                result=CategorizationResult(
                    category_id=category_id,
                    canonical_merchant_name=merchant_name,
                    source="user",
                    confidence=Decimal("1.000"),
                ),
                normalized_merchant=normalized,
                supersede_existing=True,
            )
            matching_transactions_updated = 1

        self.session.commit()
        return {
            "transaction_id": transaction_id,
            "category_id": category_id,
            "canonical_merchant_name": merchant_name,
            "matching_transactions_updated": matching_transactions_updated,
        }

    def _transactions_without_active_category(self) -> list[RawTransaction]:
        active_categorized = select(TransactionCategorization.transaction_id).where(
            TransactionCategorization.status == "active"
        )
        return self.session.scalars(
            select(RawTransaction)
            .where(RawTransaction.id.not_in(active_categorized))
            .order_by(RawTransaction.created_at)
        ).all()

    def _active_aliases(self) -> list[MerchantAlias]:
        return self.session.scalars(
            select(MerchantAlias)
            .where(MerchantAlias.status == "active")
            .order_by(MerchantAlias.normalized_pattern.desc())
        ).all()

    def _match_alias(self, normalized_description: str, aliases: list[MerchantAlias]) -> MerchantAlias | None:
        matches = [
            alias
            for alias in aliases
            if alias.normalized_pattern == normalized_description
            or f" {alias.normalized_pattern} " in f" {normalized_description} "
        ]
        if not matches:
            return None
        return max(matches, key=lambda alias: len(alias.normalized_pattern))

    def _set_transaction_category(
        self,
        transaction: RawTransaction,
        result: CategorizationResult,
        normalized_merchant: str,
        supersede_existing: bool = False,
    ) -> None:
        if supersede_existing:
            self._supersede_active(transaction.id)
        self.session.add(
            TransactionCategorization(
                transaction_id=transaction.id,
                normalized_merchant=normalized_merchant,
                canonical_merchant_name=result.canonical_merchant_name,
                category_id=result.category_id,
                source=result.source,
                confidence=result.confidence,
                status="active",
            )
        )

    def _supersede_active(self, transaction_id: str) -> None:
        active_rows = self.session.scalars(
            select(TransactionCategorization).where(
                TransactionCategorization.transaction_id == transaction_id,
                TransactionCategorization.status == "active",
            )
        ).all()
        for row in active_rows:
            row.status = "superseded"

    def _upsert_jobs(self, unknowns: dict[str, list[RawTransaction]]) -> int:
        queued = 0
        for normalized_merchant, transactions in unknowns.items():
            if not normalized_merchant:
                continue
            existing = self.session.scalar(
                select(CategorizationJob).where(CategorizationJob.normalized_merchant == normalized_merchant)
            )
            examples = [transaction.description for transaction in transactions[:5]]
            if existing:
                existing.example_descriptions = json.dumps(examples)
                existing.transaction_count = len(transactions)
                if existing.status == "complete":
                    existing.status = "pending"
                continue
            self.session.add(
                CategorizationJob(
                    normalized_merchant=normalized_merchant,
                    example_descriptions=json.dumps(examples),
                    transaction_count=len(transactions),
                    status="pending",
                )
            )
            queued += 1
        return queued

    def _upsert_alias(
        self,
        normalized_pattern: str,
        canonical_merchant_name: str,
        category_id: str,
        source: str,
        confidence: Decimal,
        status: str,
    ) -> MerchantAlias | None:
        alias = self.session.scalar(
            select(MerchantAlias).where(MerchantAlias.normalized_pattern == normalized_pattern)
        )
        if alias:
            alias.canonical_merchant_name = canonical_merchant_name
            alias.category_id = category_id
            alias.source = source
            alias.confidence = confidence
            alias.status = status
            return None
        alias = MerchantAlias(
            normalized_pattern=normalized_pattern,
            canonical_merchant_name=canonical_merchant_name,
            category_id=category_id,
            source=source,
            confidence=confidence,
            status=status,
        )
        self.session.add(alias)
        return alias

    def _apply_alias_to_matching_transactions(self, normalized_pattern: str) -> int:
        alias = self.session.scalar(
            select(MerchantAlias).where(
                MerchantAlias.normalized_pattern == normalized_pattern,
                MerchantAlias.status == "active",
            )
        )
        if alias is None:
            return 0

        updated = 0
        transactions = self.session.scalars(select(RawTransaction)).all()
        for transaction in transactions:
            normalized = self.normalizer.normalize(transaction.description)
            if alias.normalized_pattern not in normalized:
                continue
            self._supersede_active(transaction.id)
            self._set_transaction_category(
                transaction=transaction,
                result=CategorizationResult(
                    category_id=alias.category_id,
                    canonical_merchant_name=alias.canonical_merchant_name,
                    source="user",
                    confidence=alias.confidence,
                ),
                normalized_merchant=normalized,
            )
            updated += 1
        return updated

    def _require_category(self, category_id: str) -> None:
        category = self.session.get(CategoryTaxonomy, category_id)
        if category is None or not category.is_active:
            raise ValueError(f"Unknown category_id: {category_id}")
        if category.parent_category_id is None:
            raise ValueError(f"Category must be a subcategory: {category_id}")

    def _title_from_normalized(self, normalized: str) -> str:
        return normalized.title() if normalized else "Unknown Merchant"

    def _llm_categorize_jobs(self, jobs: list[CategorizationJob], categories: list[dict]) -> dict[str, dict[str, Any]]:
        system_prompt = (
            "You categorize personal finance merchants. Return only valid JSON. "
            "Choose category_id only from the supplied subcategories. Do not return parent category IDs "
            "and do not invent categories. Keep merchant names short and return one result per merchant."
        )
        user_prompt = json.dumps(
            {
                "categories": categories,
                "merchants": [
                    {
                        "normalized_merchant": job.normalized_merchant,
                        "example_descriptions": json.loads(job.example_descriptions),
                        "transaction_count": job.transaction_count,
                    }
                    for job in jobs
                ],
                "response_schema": {
                    "results": [
                        {
                            "normalized_merchant": "string",
                            "canonical_merchant_name": "string",
                            "category_id": "string",
                            "confidence": "number from 0 to 1, two decimal places",
                        }
                    ]
                },
            },
            indent=2,
        )
        try:
            raw_response = self.llm_provider.complete(system_prompt, user_prompt)
            payload = _extract_json(raw_response)
            if "results" not in payload or not isinstance(payload["results"], list):
                raise ValueError("LLM response JSON must contain a results list.")
            return {item["normalized_merchant"]: item for item in payload["results"]}
        except ConfigurationError:
            raise
        except Exception as exc:
            logger.exception("LLM categorization failed for %s merchant jobs.", len(jobs))
            raise AgentExecutionError("LLM categorization failed.") from exc


def _extract_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()
    return json.loads(text)
