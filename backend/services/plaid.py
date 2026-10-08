from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.common.exceptions import ConfigurationError, PlaidIntegrationError
from backend.core.config import settings
from backend.db.models import FinancialAccount, IngestionRun, PlaidItem, RawTransaction, TransactionCategorization
from backend.services.categorization import CategorizationService


class PlaidService:
    """Owns Plaid API calls and maps Plaid data into local ingestion tables."""

    def __init__(self, session: Session):
        self.session = session

    def create_link_token(self) -> dict:
        settings.require_plaid_configuration()
        request = self._model(
            "link_token_create_request",
            "LinkTokenCreateRequest",
            products=self._products(),
            client_name=settings.plaid_client_name,
            country_codes=self._country_codes(),
            language="en",
            user=self._model("link_token_create_request_user", "LinkTokenCreateRequestUser", client_user_id="local-user"),
        )
        response = self._client().link_token_create(request)
        return {"link_token": self._value(response, "link_token"), "expiration": self._value(response, "expiration")}

    def exchange_public_token(self, public_token: str, metadata: dict[str, Any] | None = None) -> dict:
        settings.require_plaid_configuration()
        if not public_token.strip():
            raise PlaidIntegrationError("Plaid public token is required.")

        try:
            request = self._model(
                "item_public_token_exchange_request",
                "ItemPublicTokenExchangeRequest",
                public_token=public_token,
            )
            response = self._client().item_public_token_exchange(request)
            item_id = self._value(response, "item_id")
            access_token = self._value(response, "access_token")
            institution = (metadata or {}).get("institution") or {}

            item = self.session.scalar(select(PlaidItem).where(PlaidItem.item_id == item_id))
            if item is None:
                item = PlaidItem(item_id=item_id, access_token=access_token)
                self.session.add(item)
            item.access_token = access_token
            item.institution_id = institution.get("institution_id")
            item.institution_name = institution.get("name")
            item.status = "active"

            self.session.flush()
            accounts_upserted = self._sync_accounts(item)
            self.session.commit()
            return {
                "item_id": item.item_id,
                "institution_name": item.institution_name,
                "accounts_upserted": accounts_upserted,
            }
        except PlaidIntegrationError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise PlaidIntegrationError("Plaid Item could not be saved locally.") from exc
        except Exception as exc:
            self.session.rollback()
            raise PlaidIntegrationError("Plaid public token exchange failed.") from exc

    def sync_transactions(self, item_id: str | None = None) -> dict:
        settings.require_plaid_configuration()
        items = self._items_for_sync(item_id)
        if not items:
            return {"items_synced": 0, "transactions_added": 0, "transactions_modified": 0, "transactions_removed": 0}

        totals = {"items_synced": 0, "transactions_added": 0, "transactions_modified": 0, "transactions_removed": 0}
        try:
            for item in items:
                item_totals = self._sync_item_transactions(item)
                for key, value in item_totals.items():
                    totals[key] += value
                totals["items_synced"] += 1
            CategorizationService(self.session).apply_known_aliases_and_queue_unknowns(commit=False)
            self.session.commit()
            return totals
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise PlaidIntegrationError("Plaid transactions could not be saved locally.") from exc
        except Exception as exc:
            self.session.rollback()
            raise PlaidIntegrationError("Plaid transaction sync failed.") from exc

    def list_items(self) -> list[dict]:
        rows = self.session.scalars(select(PlaidItem).order_by(PlaidItem.created_at.desc())).all()
        return [
            {
                "item_id": item.item_id,
                "institution_name": item.institution_name,
                "status": item.status,
                "has_cursor": item.sync_cursor is not None,
                "accounts": [
                    {
                        "account_id": account.source_account_key,
                        "name": account.name,
                        "official_name": account.official_name,
                        "mask": account.mask,
                        "type": account.account_type,
                        "subtype": account.account_subtype,
                        "available_balance": account.available_balance,
                        "current_balance": account.current_balance,
                        "iso_currency_code": account.iso_currency_code,
                    }
                    for account in item.accounts
                ],
            }
            for item in rows
        ]

    def _sync_item_transactions(self, item: PlaidItem) -> dict[str, int]:
        totals = {"transactions_added": 0, "transactions_modified": 0, "transactions_removed": 0}
        has_more = True
        cursor = item.sync_cursor
        import_record = IngestionRun(
            source="plaid",
            filename=f"{item.institution_name or item.item_id} Plaid sync",
            source_fingerprint=f"plaid:{item.item_id}:{cursor or 'initial'}:{uuid4()}",
        )
        self.session.add(import_record)
        self.session.flush()

        while has_more:
            request_args: dict[str, Any] = {"access_token": item.access_token, "count": 500}
            if cursor:
                request_args["cursor"] = cursor
            request = self._model("transactions_sync_request", "TransactionsSyncRequest", **request_args)
            response = self._client().transactions_sync(request)
            for transaction in self._value(response, "added", []) or []:
                self._upsert_transaction(item, import_record, transaction)
                totals["transactions_added"] += 1
            for transaction in self._value(response, "modified", []) or []:
                self._upsert_transaction(item, import_record, transaction)
                totals["transactions_modified"] += 1
            removed_ids = [self._value(transaction, "transaction_id") for transaction in self._value(response, "removed", []) or []]
            totals["transactions_removed"] += self._remove_transactions([id_ for id_ in removed_ids if id_])

            cursor = self._value(response, "next_cursor")
            has_more = bool(self._value(response, "has_more", False))

        item.sync_cursor = cursor
        return totals

    def _upsert_transaction(self, item: PlaidItem, import_record: IngestionRun, transaction: Any) -> None:
        plaid_transaction_id = self._value(transaction, "transaction_id")
        existing = self.session.scalar(
            select(RawTransaction).where(
                RawTransaction.source == "plaid",
                RawTransaction.source_transaction_key == plaid_transaction_id,
            )
        )
        account = self.session.scalar(
            select(FinancialAccount).where(
                FinancialAccount.source == "plaid",
                FinancialAccount.source_account_key == self._value(transaction, "account_id"),
            )
        )
        amount = Decimal(str(self._value(transaction, "amount", 0))).quantize(Decimal("0.01"))
        target = existing or RawTransaction(
            ingestion_run_id=import_record.id,
            source="plaid",
            source_transaction_key=plaid_transaction_id,
        )
        target.account_id = account.id if account else None
        target.posted_date = self._parse_date(self._value(transaction, "date"))
        target.description = self._description(transaction)
        target.amount = abs(amount)
        target.direction = "credit" if amount < 0 else "debit"
        target.account_name = self._account_name(item, account)
        target.category_hint = self._category_hint(transaction)
        target.page_number = None
        target.row_number = None
        if existing is None:
            self.session.add(target)

    def _remove_transactions(self, transaction_ids: list[str]) -> int:
        if not transaction_ids:
            return 0
        local_ids = self.session.scalars(
            select(RawTransaction.id).where(
                RawTransaction.source == "plaid",
                RawTransaction.source_transaction_key.in_(transaction_ids),
            )
        ).all()
        if not local_ids:
            return 0
        self.session.execute(delete(TransactionCategorization).where(TransactionCategorization.transaction_id.in_(local_ids)))
        result = self.session.execute(delete(RawTransaction).where(RawTransaction.id.in_(local_ids)))
        return int(result.rowcount or 0)

    def _sync_accounts(self, item: PlaidItem) -> int:
        request = self._model("accounts_get_request", "AccountsGetRequest", access_token=item.access_token)
        response = self._client().accounts_get(request)
        upserted = 0
        for account_payload in self._value(response, "accounts", []) or []:
            account_id = self._value(account_payload, "account_id")
            account = self.session.scalar(
                select(FinancialAccount).where(
                    FinancialAccount.source == "plaid",
                    FinancialAccount.source_account_key == account_id,
                )
            )
            if account is None:
                account = FinancialAccount(
                    source="plaid",
                    source_account_key=account_id,
                    plaid_item_id=item.item_id,
                    name="",
                )
                self.session.add(account)
            account.plaid_item_id = item.item_id
            balances = self._value(account_payload, "balances", {}) or {}
            account.name = self._value(account_payload, "name") or "Plaid account"
            account.official_name = self._value(account_payload, "official_name")
            account.mask = self._value(account_payload, "mask")
            account.account_type = str(self._value(account_payload, "type") or "")
            account.account_subtype = str(self._value(account_payload, "subtype") or "")
            account.available_balance = self._decimal_or_none(self._value(balances, "available"))
            account.current_balance = self._decimal_or_none(self._value(balances, "current"))
            account.iso_currency_code = self._value(balances, "iso_currency_code")
            upserted += 1
        return upserted

    def _items_for_sync(self, item_id: str | None) -> list[PlaidItem]:
        statement = select(PlaidItem).where(PlaidItem.status == "active").order_by(PlaidItem.created_at.asc())
        if item_id:
            statement = statement.where(PlaidItem.item_id == item_id)
        return list(self.session.scalars(statement).all())

    def _client(self) -> Any:
        try:
            import plaid
            from plaid.api import plaid_api
        except ImportError as exc:
            raise ConfigurationError("Plaid SDK is not installed. Install plaid-python.") from exc

        environment = settings.plaid_env.strip().lower()
        host = plaid.Environment.Sandbox if environment == "sandbox" else plaid.Environment.Production
        configuration = plaid.Configuration(
            host=host,
            api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret},
        )
        return plaid_api.PlaidApi(plaid.ApiClient(configuration))

    def _products(self) -> list[Any]:
        products_class = self._class("products", "Products")
        return [products_class(product) for product in settings.plaid_product_list]

    def _country_codes(self) -> list[Any]:
        country_code_class = self._class("country_code", "CountryCode")
        return [country_code_class(country) for country in settings.plaid_country_code_list]

    def _model(self, module_name: str, class_name: str, **kwargs: Any) -> Any:
        return self._class(module_name, class_name)(**kwargs)

    def _class(self, module_name: str, class_name: str) -> Any:
        try:
            module = __import__(f"plaid.model.{module_name}", fromlist=[class_name])
        except ImportError as exc:
            raise ConfigurationError("Plaid SDK is not installed. Install plaid-python.") from exc
        return getattr(module, class_name)

    def _value(self, payload: Any, key: str, default: Any = None) -> Any:
        if payload is None:
            return default
        if isinstance(payload, dict):
            return payload.get(key, default)
        return getattr(payload, key, default)

    def _parse_date(self, value: Any) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    def _description(self, transaction: Any) -> str:
        merchant = self._value(transaction, "merchant_name")
        return merchant or self._value(transaction, "name") or "Plaid transaction"

    def _category_hint(self, transaction: Any) -> str | None:
        personal_finance_category = self._value(transaction, "personal_finance_category")
        detailed = self._value(personal_finance_category, "detailed")
        primary = self._value(personal_finance_category, "primary")
        if detailed and primary:
            return f"{primary}:{detailed}"
        return detailed or primary

    def _account_name(self, item: PlaidItem, account: FinancialAccount | None) -> str:
        if account and item.institution_name:
            return f"{item.institution_name} - {account.name}"
        if account:
            return account.name
        return item.institution_name or "Plaid"

    def _decimal_or_none(self, value: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value)).quantize(Decimal("0.01"))
