from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from backend.common.exceptions import ConfigurationError, PlaidIntegrationError
from backend.db.models import PlaidItem
from backend.services import plaid as plaid_module
from backend.services.plaid import PlaidService
from backend.services.plaid_vault import PlaidVault


class FakeSession:
    def __init__(self, items=None):
        self.items = list(items or [])

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.items)

    def scalar(self, _statement):
        return self.items[0] if self.items else None

    def add(self, item):
        self.items.append(item)

    def flush(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


def make_vault(tmp_path, key=None, environment="sandbox"):
    return PlaidVault(
        key=key or Fernet.generate_key().decode(), path=tmp_path / "vault.enc",
        environment=environment, client_id="test-client",
    )


def test_vault_migrates_legacy_token_and_restores_item_after_database_reset(tmp_path):
    vault = make_vault(tmp_path)
    session = FakeSession([PlaidItem(
        item_id="item-sandbox-1", access_token="access-sandbox-secret",
        institution_id="ins_test", institution_name="Test Bank", sync_cursor="old-cursor", status="active",
    )])

    assert vault.restore(session) == []
    assert session.items[0].access_token.startswith("fernet:")
    assert vault.open(session.items[0].access_token) == "access-sandbox-secret"
    assert b"access-sandbox-secret" not in vault.path.read_bytes()
    assert b"item-sandbox-1" not in vault.path.read_bytes()

    rebuilt = FakeSession()
    assert vault.restore(rebuilt) == ["item-sandbox-1"]
    assert rebuilt.items[0].sync_cursor is None
    assert rebuilt.items[0].institution_name == "Test Bank"
    assert vault.open(rebuilt.items[0].access_token) == "access-sandbox-secret"


def test_vault_rejects_wrong_key_and_environment_without_erasing_file(tmp_path):
    key = Fernet.generate_key().decode()
    vault = make_vault(tmp_path, key=key)
    vault.save_item("item-1", "access-secret", None, None)
    original = vault.path.read_bytes()

    with pytest.raises(ConfigurationError):
        make_vault(tmp_path).restore(FakeSession())
    with pytest.raises(ConfigurationError):
        make_vault(tmp_path, key=key, environment="production").restore(FakeSession())
    assert vault.path.read_bytes() == original


def test_update_mode_uses_existing_access_token_without_products(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    item = PlaidItem(item_id="item-1", access_token=vault.seal("access-secret"), status="active")
    session = FakeSession([item])
    service = PlaidService(session)
    requests = []
    monkeypatch.setattr(plaid_module, "PlaidVault", lambda: vault)
    monkeypatch.setattr(plaid_module, "settings", SimpleNamespace(
        require_plaid_configuration=lambda: None, plaid_client_name="Finance Guardian",
    ))
    monkeypatch.setattr(service, "_country_codes", lambda: ["US"])
    monkeypatch.setattr(service, "_model", lambda _module, _name, **kwargs: kwargs)
    monkeypatch.setattr(service, "_client", lambda: SimpleNamespace(
        link_token_create=lambda request: requests.append(request) or {"link_token": "link-1"},
    ))

    assert service.create_link_token(item_id="item-1")["link_token"] == "link-1"
    assert requests[0]["access_token"] == "access-secret"
    assert "products" not in requests[0]


def test_exchanged_token_survives_database_failure(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    service = PlaidService(FakeSession())
    monkeypatch.setattr(plaid_module, "PlaidVault", lambda: vault)
    monkeypatch.setattr(plaid_module, "settings", SimpleNamespace(require_plaid_configuration=lambda: None))
    monkeypatch.setattr(service, "_model", lambda _module, _name, **kwargs: kwargs)
    monkeypatch.setattr(service, "_client", lambda: SimpleNamespace(
        item_public_token_exchange=lambda _request: {
            "item_id": "item-1", "access_token": "access-secret",
        },
    ))
    monkeypatch.setattr(service, "_sync_accounts", lambda _item: (_ for _ in ()).throw(RuntimeError("database error")))

    with pytest.raises(PlaidIntegrationError):
        service.exchange_public_token("public-token", {"institution": {"name": "Test Bank"}})
    rebuilt = FakeSession()
    assert vault.restore(rebuilt) == ["item-1"]
    assert vault.open(rebuilt.items[0].access_token) == "access-secret"
