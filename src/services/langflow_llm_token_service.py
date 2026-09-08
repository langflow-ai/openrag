"""Short-lived tokens for Langflow-to-backend LLM proxy calls.

Same family as ingest tokens: minted per Langflow run, scoped to the LLM
proxy, and useless on the rest of `/v1`. Langflow's OpenAI client sends the
token as `Authorization: Bearer` (`OPENRAG_LLM_TOKEN`). SDK and MCP callers keep
using the user JWT or an `orag_` key.
"""

from __future__ import annotations

import time
import uuid

import jwt

from services.langflow_ingest_token_service import _resolve_default_signing_config
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

LANGFLOW_LLM_AUDIENCE = "openrag-langflow-llm"
LANGFLOW_LLM_SCOPE = "llm:proxy"
LANGFLOW_HOP_AUDIENCES = frozenset(
    {
        LANGFLOW_LLM_AUDIENCE,
        "openrag-langflow-ingest",
    }
)


def langflow_hop_audience(token: str) -> str | None:
    """Unverified `aud` when `token` is a Langflow hop token, else None."""
    if not token or token.startswith("orag_"):
        return None
    try:
        claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
        )
    except jwt.PyJWTError:
        return None
    aud = claims.get("aud")
    values = aud if isinstance(aud, list) else [aud]
    for value in values:
        if value in LANGFLOW_HOP_AUDIENCES:
            return str(value)
    return None


class LangflowLlmTokenService:
    """Mint and validate per-run LLM proxy tokens.

    A token is valid for many completions/embeddings calls during one Langflow
    run. It is not one-shot; revoke is optional. Expiry is the bound.
    """

    audience = LANGFLOW_LLM_AUDIENCE
    scope = LANGFLOW_LLM_SCOPE

    def __init__(self, secret: str | None = None, ttl_seconds: int | None = None):
        if secret is not None:
            self._signing_key = secret
            self._verification_key = secret
            self.algorithm = "HS256"
        else:
            self._signing_key, self._verification_key, self.algorithm = (
                _resolve_default_signing_config()
            )
        from config.settings import get_langflow_llm_proxy_ttl_seconds

        self.ttl_seconds = max(ttl_seconds or get_langflow_llm_proxy_ttl_seconds(), 1)

    def create_token(
        self,
        *,
        user_id: str,
        email: str | None = None,
        name: str | None = None,
    ) -> str:
        now = int(time.time())
        subject = (user_id or "").strip() or "anonymous"
        payload = {
            "aud": self.audience,
            "scope": self.scope,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + self.ttl_seconds,
            "sub": subject,
            "user_id": subject,
            "email": (email or subject),
            "name": (name or subject),
        }
        return jwt.encode(payload, self._signing_key, algorithm=self.algorithm)

    def validate_token(self, token: str) -> User:
        try:
            payload = jwt.decode(
                token,
                self._verification_key,
                algorithms=[self.algorithm],
                audience=self.audience,
            )
        except jwt.PyJWTError as e:
            logger.warning(
                "Invalid Langflow LLM proxy token",
                jwt_error=e.__class__.__name__,
                detail=str(e),
            )
            raise ValueError("Invalid Langflow LLM proxy token") from e

        if payload.get("scope") != self.scope:
            raise ValueError("Langflow LLM proxy token has invalid scope")

        user_id = str(payload.get("user_id") or payload.get("sub") or "").strip()
        if not user_id:
            raise ValueError("Langflow LLM proxy token is missing user_id")

        return User(
            user_id=user_id,
            email=str(payload.get("email") or user_id),
            name=str(payload.get("name") or user_id),
            provider="langflow_llm",
        )
