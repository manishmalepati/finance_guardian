"""Encrypted Plaid credentials that survive disposal of the development database."""

import hashlib
import json
import os
from pathlib import Path
import tempfile

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.common.exceptions import ConfigurationError
from backend.core.config import settings
from backend.db.models import PlaidItem


class PlaidVault:
    def __init__(self, *, key: str | None = None, path: str | Path | None = None,
                 environment: str | None = None, client_id: str | None = None):
        secret = key if key is not None else settings.plaid_vault_key
        if not secret.strip():
            raise ConfigurationError("Plaid vault is not configured. Set PLAID_VAULT_KEY before connecting or syncing a bank.")
        try:
            self.cipher = Fernet(secret.strip().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ConfigurationError("PLAID_VAULT_KEY must be a valid Fernet key.") from exc
        self.environment = (environment if environment is not None else settings.plaid_env).strip().lower()
        configured_path = path if path is not None else settings.plaid_vault_path
        self.path = Path(configured_path or f".local/plaid-vault-{self.environment}.enc")
        self.client_digest = hashlib.sha256(
            (client_id if client_id is not None else settings.plaid_client_id).encode("utf-8")
        ).hexdigest()

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "environment": self.environment,
                    "client_digest": self.client_digest, "items": {}}
        if self.path.is_symlink():
            raise ConfigurationError("Plaid vault path must not be a symbolic link.")
        try:
            payload = json.loads(self.cipher.decrypt(self.path.read_bytes()))
        except (OSError, InvalidToken, ValueError, TypeError) as exc:
            raise ConfigurationError("Plaid vault cannot be read. Check its key and file before connecting again.") from exc
        if (not isinstance(payload, dict) or payload.get("version") != 1
                or payload.get("environment") != self.environment
                or payload.get("client_digest") != self.client_digest
                or not isinstance(payload.get("items"), dict)):
            raise ConfigurationError("Plaid vault belongs to a different configuration or has an unsupported format.")
        return payload

    def _write(self, payload: dict) -> None:
        if self.path.is_symlink():
            raise ConfigurationError("Plaid vault path must not be a symbolic link.")
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            encrypted = self.cipher.encrypt(json.dumps(payload, sort_keys=True).encode("utf-8"))
            descriptor, temporary = tempfile.mkstemp(prefix=".plaid-vault-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    os.chmod(temporary, 0o600)
                    stream.write(encrypted)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError as exc:
            raise ConfigurationError("Plaid vault could not be saved. Check its directory permissions.") from exc

    def preflight(self) -> None:
        """Fail before Link opens if encrypted storage is unavailable."""
        self._write(self._read())

    def seal(self, access_token: str) -> str:
        return "fernet:" + self.cipher.encrypt(access_token.encode("utf-8")).decode("ascii")

    def open(self, stored_token: str) -> str:
        if not stored_token.startswith("fernet:"):
            raise ConfigurationError("Plaid database token has not been migrated to the encrypted vault.")
        try:
            return self.cipher.decrypt(stored_token.removeprefix("fernet:").encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise ConfigurationError("Plaid database token cannot be decrypted with PLAID_VAULT_KEY.") from exc

    def save_item(self, item_id: str, access_token: str, institution_id: str | None,
                  institution_name: str | None) -> None:
        payload = self._read()
        payload["items"][item_id] = {
            "access_token": access_token,
            "institution_id": institution_id,
            "institution_name": institution_name,
        }
        self._write(payload)

    def restore(self, session: Session) -> list[str]:
        """Migrate existing rows, then restore missing Items without old cursors."""
        payload = self._read()
        entries = payload["items"]
        database_items = {item.item_id: item for item in session.scalars(select(PlaidItem)).all()}
        changed_vault = False
        for item_id, item in database_items.items():
            if item_id not in entries:
                token = self.open(item.access_token) if item.access_token.startswith("fernet:") else item.access_token
                entries[item_id] = {
                    "access_token": token,
                    "institution_id": item.institution_id,
                    "institution_name": item.institution_name,
                }
                changed_vault = True
        if changed_vault:
            self._write(payload)

        restored = []
        for item_id, entry in entries.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("access_token"), str):
                raise ConfigurationError("Plaid vault has an invalid Item record.")
            item = database_items.get(item_id)
            if item is None:
                item = PlaidItem(item_id=item_id, sync_cursor=None, status="active")
                session.add(item)
                restored.append(item_id)
            item.access_token = self.seal(entry["access_token"])
            item.institution_id = entry.get("institution_id")
            item.institution_name = entry.get("institution_name")
        if database_items or restored:
            session.commit()
        return restored
