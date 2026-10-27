"""Server-side Gmail OAuth for a single local development account."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.common.exceptions import ConfigurationError, GmailIntegrationError
from backend.core.config import settings
from backend.receipts.models import GmailConnection, OAuthState

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class GmailAuth:
    def __init__(self, session: Session, client: httpx.Client | None = None):
        self.session = session
        self.client = client or httpx.Client(timeout=20)

    @staticmethod
    def _cipher() -> Fernet:
        settings.require_gmail_configuration()
        try:
            return Fernet(settings.gmail_token_key.strip().encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise ConfigurationError("GMAIL_TOKEN_KEY must be a valid Fernet key.") from exc

    def begin(self) -> dict:
        self._cipher()
        if self.session.scalar(select(GmailConnection).where(GmailConnection.status == "active")):
            raise GmailIntegrationError("Disconnect the current Gmail account before connecting another.")
        self.session.execute(delete(OAuthState).where(OAuthState.expires_at < datetime.now(UTC)))
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.session.add(OAuthState(
            state=state, code_verifier=verifier,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        ))
        self.session.commit()
        params = {
            "client_id": settings.gmail_client_id,
            "redirect_uri": settings.gmail_redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return {"authorization_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}

    def complete(self, code: str, state: str) -> GmailConnection:
        self._cipher()
        pending = self.session.get(OAuthState, state)
        if pending is None or pending.expires_at < datetime.now(UTC):
            raise GmailIntegrationError("Gmail authorization expired. Start the connection again.")
        verifier = pending.code_verifier
        self.session.delete(pending)
        self.session.commit()
        try:
            token_response = self.client.post(TOKEN_URL, data={
                "code": code, "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "redirect_uri": settings.gmail_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            })
            token_response.raise_for_status()
            tokens = token_response.json()
            access_token = tokens["access_token"]
            profile_response = self.client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_response.raise_for_status()
            email_address = profile_response.json()["emailAddress"].lower()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise GmailIntegrationError("Gmail authorization could not be completed.") from exc
        connection = self.session.scalar(select(GmailConnection).where(GmailConnection.email_address == email_address))
        refresh_token = tokens.get("refresh_token")
        if not refresh_token and (connection is None or not connection.encrypted_refresh_token):
            raise GmailIntegrationError("Gmail did not return a refresh token. Reconnect and approve access.")
        if connection is None:
            connection = GmailConnection(email_address=email_address, encrypted_refresh_token="")
            self.session.add(connection)
        if refresh_token:
            connection.encrypted_refresh_token = self._cipher().encrypt(refresh_token.encode()).decode()
        connection.status = "active"
        self.session.commit()
        return connection

    def access_token(self, connection: GmailConnection) -> str:
        if connection.status != "active" or not connection.encrypted_refresh_token:
            raise GmailIntegrationError("Gmail connection needs reauthorization.")
        try:
            refresh_token = self._cipher().decrypt(connection.encrypted_refresh_token.encode()).decode()
        except (InvalidToken, UnicodeError) as exc:
            raise GmailIntegrationError("Stored Gmail credentials cannot be opened.") from exc
        try:
            response = self.client.post(TOKEN_URL, data={
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            })
            response.raise_for_status()
            return response.json()["access_token"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {400, 401}:
                raise GmailIntegrationError("Gmail token refresh is temporarily unavailable.") from exc
            connection.status = "reauthorize"
            self.session.commit()
            raise GmailIntegrationError("Gmail authorization expired. Reconnect Gmail.") from exc
        except (httpx.RequestError, ValueError, KeyError) as exc:
            raise GmailIntegrationError("Gmail token refresh is temporarily unavailable.") from exc

    def disconnect(self, connection: GmailConnection) -> bool:
        """Clear local credentials even when Google's revocation endpoint is unavailable."""
        revoked = False
        if connection.encrypted_refresh_token:
            try:
                token = self._cipher().decrypt(connection.encrypted_refresh_token.encode()).decode()
                response = self.client.post(REVOKE_URL, data={"token": token})
                revoked = response.status_code == 200
            except (httpx.HTTPError, InvalidToken, UnicodeError, ConfigurationError):
                pass
        connection.encrypted_refresh_token = ""
        connection.status = "disconnected"
        self.session.commit()
        return revoked
