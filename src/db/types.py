"""Custom SQLAlchemy types.

EncryptedString reuses utils.encryption (AES-256-GCM + PBKDF2) so we never
introduce a parallel crypto path. Stored on disk as a JSON envelope; if no
master secret is configured it falls through to plaintext (matching the
behavior already documented in encryption.py).
"""

import json
from typing import Optional

from sqlalchemy.types import String, TypeDecorator

from utils.encryption import (
    ENCRYPTION_ALGORITHM,
    decrypt_secret,
    encrypt_secret,
    get_master_secret,
)


class EncryptedString(TypeDecorator):
    """A TEXT column whose value is transparently encrypted at rest."""

    impl = String
    cache_ok = True

    def __init__(self, tenant_id: str = "user_pii", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant_id = tenant_id

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        if not value:
            return value
        if get_master_secret() is None:
            return value
        envelope = encrypt_secret(value, tenant_id=self._tenant_id)
        if isinstance(envelope, dict):
            return json.dumps(envelope, separators=(",", ":"))
        return envelope

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        if not value:
            return value
        try:
            payload = json.loads(value)
        except (ValueError, TypeError):
            return value
        if (
            isinstance(payload, dict)
            and payload.get("algorithm") == ENCRYPTION_ALGORITHM
            and "ciphertext" in payload
        ):
            return decrypt_secret(payload, expected_tenant_id=self._tenant_id)
        return value
