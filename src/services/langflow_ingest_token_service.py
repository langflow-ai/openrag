"""Short-lived tokens for Langflow-to-backend ingest callbacks."""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
from cachetools import TTLCache
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed448, ed25519, rsa

from config.settings import LANGFLOW_INGEST_CALLBACK_TTL_SECONDS
from services.document_index_writer import DocumentIndexContext
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _resolve_default_signing_config() -> tuple[Any, Any, str]:
    """Prefer JWT_SIGNING_KEY when set; otherwise fall back to SESSION_SECRET."""
    from config.settings import JWT_SIGNING_KEY, SESSION_SECRET

    signing_key = JWT_SIGNING_KEY
    if not signing_key:
        return SESSION_SECRET, SESSION_SECRET, "HS256"

    if signing_key.lstrip().startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(signing_key.encode(), password=None)
        public_key = key.public_key()

        if isinstance(key, rsa.RSAPrivateKey):
            algorithm = "RS256"
        elif isinstance(key, ec.EllipticCurvePrivateKey):
            curve = key.curve
            if isinstance(curve, ec.SECP256R1):
                algorithm = "ES256"
            elif isinstance(curve, ec.SECP384R1):
                algorithm = "ES384"
            elif isinstance(curve, ec.SECP521R1):
                algorithm = "ES512"
            else:
                raise ValueError(f"Unsupported EC curve: {curve.name}")
        elif isinstance(key, (ed25519.Ed25519PrivateKey, ed448.Ed448PrivateKey)):
            algorithm = "EdDSA"
        else:
            raise ValueError(f"Unsupported private key type: {type(key)}")

        return key, public_key, algorithm

    return signing_key, signing_key, "HS256"


class LangflowIngestTokenService:
    """Mint and validate per-run ingest callback tokens.

    A token is valid for one Langflow ingest run. It can be used for multiple
    batch callbacks, then is marked finalized when the component posts the final
    batch.
    """

    audience = "openrag-langflow-ingest"

    def __init__(self, secret: str | None = None, ttl_seconds: int | None = None):
        if secret is not None:
            self._signing_key = secret
            self._verification_key = secret
            self.algorithm = "HS256"
        else:
            self._signing_key, self._verification_key, self.algorithm = (
                _resolve_default_signing_config()
            )
        self.ttl_seconds = max(ttl_seconds or LANGFLOW_INGEST_CALLBACK_TTL_SECONDS, 1)
        self._finalized_jtis: TTLCache[str, bool] = TTLCache(
            maxsize=8192,
            ttl=self.ttl_seconds + 60,
        )
        self._revoked_jtis: TTLCache[str, bool] = TTLCache(
            maxsize=8192,
            ttl=self.ttl_seconds + 60,
        )

    def create_token(self, context: DocumentIndexContext) -> str:
        now = int(time.time())
        jti = str(uuid.uuid4())
        payload = {
            "aud": self.audience,
            "scope": "ingest:chunks",
            "jti": jti,
            "iat": now,
            "exp": now + self.ttl_seconds,
            "ctx": self._context_to_payload(context),
        }
        return jwt.encode(payload, self._signing_key, algorithm=self.algorithm)

    def validate_token(self, token: str) -> tuple[DocumentIndexContext, str]:
        try:
            payload = jwt.decode(
                token,
                self._verification_key,
                algorithms=[self.algorithm],
                audience=self.audience,
            )
        except jwt.PyJWTError as e:
            logger.warning(
                "Invalid Langflow ingest token",
                jwt_error=e.__class__.__name__,
                detail=str(e),
            )
            raise ValueError("Invalid Langflow ingest token") from e

        if payload.get("scope") != "ingest:chunks":
            raise ValueError("Langflow ingest token has invalid scope")

        jti = str(payload.get("jti") or "")
        if not jti:
            raise ValueError("Langflow ingest token is missing jti")
        if self._revoked_jtis.get(jti) or self._finalized_jtis.get(jti):
            raise ValueError("Langflow ingest token has already been consumed")

        ctx_payload = payload.get("ctx")
        if not isinstance(ctx_payload, dict):
            raise ValueError("Langflow ingest token is missing context")

        return self._payload_to_context(ctx_payload), jti

    def mark_finalized(self, jti: str) -> None:
        if jti:
            self._finalized_jtis[jti] = True

    def revoke_token(self, token: str) -> None:
        try:
            payload = jwt.decode(
                token,
                self._verification_key,
                algorithms=[self.algorithm],
                audience=self.audience,
                options={"verify_exp": False},
            )
        except jwt.PyJWTError:
            return
        jti = str(payload.get("jti") or "")
        if jti:
            self._revoked_jtis[jti] = True

    @staticmethod
    def _context_to_payload(context: DocumentIndexContext) -> dict[str, Any]:
        return {
            "document_id": context.document_id,
            "filename": context.filename,
            "mimetype": context.mimetype,
            "embedding_model": context.embedding_model,
            "owner": context.owner,
            "owner_name": context.owner_name,
            "owner_email": context.owner_email,
            "file_size": context.file_size,
            "connector_type": context.connector_type,
            "source_url": context.source_url,
            "allowed_users": list(context.allowed_users),
            "allowed_groups": list(context.allowed_groups),
            "allowed_principals": list(context.allowed_principals),
            "allowed_principal_labels": list(context.allowed_principal_labels),
            "ingest_run_id": context.ingest_run_id,
            "is_sample_data": context.is_sample_data,
            "index_name": context.index_name,
        }

    @staticmethod
    def _payload_to_context(payload: dict[str, Any]) -> DocumentIndexContext:
        file_size = payload.get("file_size")
        if file_size is not None and not isinstance(file_size, int):
            try:
                file_size = int(file_size)
            except (TypeError, ValueError):
                file_size = None
        return DocumentIndexContext(
            document_id=str(payload.get("document_id") or ""),
            filename=str(payload.get("filename") or ""),
            mimetype=str(payload.get("mimetype") or ""),
            embedding_model=str(payload.get("embedding_model") or ""),
            owner=payload.get("owner"),
            owner_name=payload.get("owner_name"),
            owner_email=payload.get("owner_email"),
            file_size=file_size,
            connector_type=payload.get("connector_type"),
            source_url=payload.get("source_url"),
            allowed_users=list(payload.get("allowed_users") or []),
            allowed_groups=list(payload.get("allowed_groups") or []),
            allowed_principals=list(payload.get("allowed_principals") or []),
            allowed_principal_labels=list(payload.get("allowed_principal_labels") or []),
            ingest_run_id=payload.get("ingest_run_id"),
            is_sample_data=bool(payload.get("is_sample_data")),
            index_name=payload.get("index_name"),
        )
