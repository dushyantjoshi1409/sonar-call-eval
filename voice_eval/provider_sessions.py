"""Process-memory credential vault for isolated, expiring browser sessions."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from voice_eval.config import Settings
from voice_eval.providers import ProviderConfig

SESSION_COOKIE_NAME = "voice_eval_provider_session"
ENVIRONMENT_PROVIDER_HANDLE = "environment-gemini"


@dataclass(frozen=True, slots=True)
class ProviderSession:
    """Opaque identifiers plus a private provider config held only in memory."""

    cookie_token: str
    credential_handle: str
    config: ProviderConfig
    expires_at: datetime


class ProviderSessionVault:
    """Thread-safe credential storage isolated by opaque HttpOnly cookie tokens."""

    def __init__(self, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("provider session TTL must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._by_cookie: dict[str, ProviderSession] = {}
        self._cookie_by_handle: dict[str, str] = {}
        self._lock = threading.RLock()

    def connect(self, config: ProviderConfig) -> ProviderSession:
        """Store a new independent credential and return its opaque identifiers."""
        now = datetime.now(UTC)
        session = ProviderSession(
            cookie_token=secrets.token_urlsafe(32),
            credential_handle=secrets.token_urlsafe(32),
            config=config,
            expires_at=now + self._ttl,
        )
        with self._lock:
            self._by_cookie[session.cookie_token] = session
            self._cookie_by_handle[session.credential_handle] = session.cookie_token
        return session

    def resolve_cookie(self, cookie_token: str | None) -> ProviderConfig | None:
        """Resolve only the credential owned by one unexpired browser cookie."""
        session = self.session_for_cookie(cookie_token)
        return session.config if session else None

    def session_for_cookie(self, cookie_token: str | None) -> ProviderSession | None:
        """Return the complete in-memory session after lazy expiry cleanup."""
        if not cookie_token:
            return None
        with self._lock:
            session = self._by_cookie.get(cookie_token)
            if session is None:
                return None
            if session.expires_at <= datetime.now(UTC):
                self._remove(session)
                return None
            return session

    def resolve_handle(self, credential_handle: str | None) -> ProviderConfig | None:
        """Resolve a job-captured handle without consulting mutable browser state."""
        if not credential_handle:
            return None
        with self._lock:
            cookie_token = self._cookie_by_handle.get(credential_handle)
        session = self.session_for_cookie(cookie_token)
        return (
            session.config if session and session.credential_handle == credential_handle else None
        )

    def clear(self, cookie_token: str | None) -> bool:
        """Clear future access for one session; an already-running call may still finish."""
        if not cookie_token:
            return False
        with self._lock:
            session = self._by_cookie.get(cookie_token)
            if session is None:
                return False
            self._remove(session)
            return True

    def public_metadata(self, cookie_token: str | None) -> dict[str, object]:
        """Describe a session without exposing its credential or opaque handle."""
        session = self.session_for_cookie(cookie_token)
        if session is None:
            return {"connected": False}
        return {
            "connected": True,
            **session.config.public_metadata(),
            "expires_at": session.expires_at.isoformat(),
        }

    def _remove(self, session: ProviderSession) -> None:
        self._by_cookie.pop(session.cookie_token, None)
        self._cookie_by_handle.pop(session.credential_handle, None)


def environment_provider_config(settings: Settings) -> ProviderConfig | None:
    """Build the legacy Gemini fallback only when its explicit gate is complete."""
    if not settings.gemini_api_key or not settings.gemini_free_tier_confirmed:
        return None
    return ProviderConfig(
        provider="gemini",
        api_key=settings.gemini_api_key,
        judge_model=settings.gemini_model,
        transcription_model=settings.gemini_model,
        free_tier_attested=True,
    )
