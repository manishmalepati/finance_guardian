from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet

from backend.receipts import gmail_auth
from backend.receipts.gmail_auth import GMAIL_SCOPE, GmailAuth
from backend.receipts.models import GmailConnection, OAuthState


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self):
        self.token_request = None

    def post(self, url, data):
        self.token_request = data
        return FakeResponse({"access_token": "temporary-access", "refresh_token": "private-refresh"})

    def get(self, url, headers):
        assert headers["Authorization"] == "Bearer temporary-access"
        return FakeResponse({"emailAddress": "demo@example.com"})


class FakeSession:
    def __init__(self):
        self.states = {}
        self.connection = None

    def scalar(self, statement):
        return self.connection

    def get(self, model, key):
        assert model is OAuthState
        return self.states.get(key)

    def add(self, row):
        if isinstance(row, OAuthState):
            self.states[row.state] = row
        elif isinstance(row, GmailConnection):
            self.connection = row

    def delete(self, row):
        self.states.pop(row.state)

    def execute(self, statement):
        pass

    def commit(self):
        pass


def test_oauth_uses_readonly_scope_state_pkce_and_encrypted_refresh_token(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(gmail_auth, "settings", SimpleNamespace(
        gmail_client_id="test-client", gmail_client_secret="test-secret",
        gmail_redirect_uri="http://localhost:8000/gmail/callback",
        gmail_token_key=key, require_gmail_configuration=lambda: None,
    ))
    session = FakeSession()
    client = FakeClient()
    auth = GmailAuth(session, client)
    url = auth.begin()["authorization_url"]
    params = parse_qs(urlparse(url).query)
    assert params["scope"] == [GMAIL_SCOPE]
    assert params["access_type"] == ["offline"]
    assert params["code_challenge_method"] == ["S256"]
    state = params["state"][0]
    assert state in session.states
    connection = auth.complete("authorization-code", state)
    assert state not in session.states
    assert client.token_request["code_verifier"]
    assert connection.encrypted_refresh_token != "private-refresh"
    assert Fernet(key.encode()).decrypt(connection.encrypted_refresh_token.encode()) == b"private-refresh"
