"""HTTP endpoints for session-scoped provider credentials and public metadata."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from voice_eval.api.dependencies import RuntimeDependency
from voice_eval.provider_sessions import SESSION_COOKIE_NAME
from voice_eval.providers import ProviderConfig, validate_custom_base_url

router = APIRouter(prefix="/api/provider-session", tags=["provider-session"])


class ProviderSessionRequest(BaseModel):
    """Browser-supplied provider selection; the key is never returned or persisted."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "openai", "groq", "custom"]
    api_key: str = Field(max_length=20_000)
    judge_model: str = Field(min_length=1, max_length=160)
    transcription_model: str | None = Field(default=None, max_length=160)
    base_url: str | None = Field(default=None, max_length=2_048)
    free_tier_attested: bool = False
    allow_paid_use: bool = False


@router.get("")
async def get_provider_session(request: Request, runtime: RuntimeDependency) -> dict[str, object]:
    """Return nonsecret metadata for the current browser session."""
    return runtime.sessions.public_metadata(request.cookies.get(SESSION_COOKIE_NAME))


@router.post("", status_code=201)
async def connect_provider_session(
    body: ProviderSessionRequest,
    request: Request,
    response: Response,
    runtime: RuntimeDependency,
) -> dict[str, object]:
    """Store one credential in process memory without testing it remotely."""
    if body.provider in {"gemini", "groq"} and not (body.free_tier_attested or body.allow_paid_use):
        raise HTTPException(
            422,
            "Confirm free-tier eligibility or explicitly opt in to possible paid use",
        )
    if body.provider in {"openai", "custom"} and not body.allow_paid_use:
        raise HTTPException(422, "Explicit paid-use opt-in is required for this provider")
    normalized_url = body.base_url
    if body.provider == "custom":
        if not body.base_url:
            raise HTTPException(422, "Custom providers require an HTTPS base URL")
        try:
            normalized_url = validate_custom_base_url(body.base_url)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    try:
        config = ProviderConfig(
            provider=body.provider,
            api_key=body.api_key,
            judge_model=body.judge_model,
            transcription_model=body.transcription_model,
            base_url=normalized_url,
            free_tier_attested=body.free_tier_attested,
            allow_paid_use=body.allow_paid_use,
        )
    except ValueError as error:
        raise HTTPException(422, "Invalid provider session configuration") from error
    runtime.sessions.clear(request.cookies.get(SESSION_COOKIE_NAME))
    session = runtime.sessions.connect(config)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session.cookie_token,
        max_age=runtime.settings.provider_session_ttl_seconds,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return runtime.sessions.public_metadata(session.cookie_token)


@router.delete("")
async def clear_provider_session(
    request: Request, response: Response, runtime: RuntimeDependency
) -> dict[str, object]:
    """Remove future credential access and expire the browser cookie."""
    runtime.sessions.clear(request.cookies.get(SESSION_COOKIE_NAME))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return {
        "connected": False,
        "detail": "Provider session cleared; an already in-flight request may still finish.",
    }
