import os
import secrets
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from typing import Union, Dict, Any, Tuple, Optional
import aiofiles
import json
from utils.logging_config import get_logger

logger = get_logger(__name__)


def get_encryption_key() -> bytes | None:
    """Retrieve the AES-256-GCM encryption key from the environment."""
    key_b64 = os.environ.get("OPENRAG_ENCRYPTION_KEY")
    if not key_b64:
        return None
    try:
        key = base64.b64decode(key_b64)
        if len(key) != 32:
            logger.error("OPENRAG_ENCRYPTION_KEY must decode to 32 bytes for AES-256-GCM")
            return None
        return key
    except Exception as e:
        logger.error(f"Failed to decode OPENRAG_ENCRYPTION_KEY: {e}")
        return None


def encrypt_secret(plaintext: str, tenant_id: str = "openrag") -> Union[Dict[str, Any], str]:
    """
    Encrypt a plaintext secret using AES-256-GCM.
    Returns a JSON-serializable dictionary with the ciphertext and metadata.
    If OPENRAG_ENCRYPTION_KEY is not set, returns the plaintext string for backward compatibility.
    """
    if not isinstance(plaintext, str) or not plaintext:
        return plaintext

    key = get_encryption_key()
    if not key:
        return plaintext

    try:
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(12)
        plaintext_bytes = plaintext.encode("utf-8")
        aad = f"tenant_id:{tenant_id}".encode("utf-8")

        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, aad)

        return {
            "version": "1.0",
            "algorithm": "AES-256-GCM",
            "tenant_id": tenant_id,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
    except Exception as e:
        logger.error(f"Failed to encrypt secret: {e}")
        # If encryption fails, fallback to plaintext so we don't lose data
        return plaintext


def decrypt_secret(payload: Union[Dict[str, Any], str]) -> str:
    """
    Decrypt a secret payload using AES-256-GCM.
    If payload is a string or does not match the encrypted structure, returns it as-is.
    """
    if not isinstance(payload, dict):
        return payload

    if payload.get("algorithm") != "AES-256-GCM" or "ciphertext" not in payload:
        return payload

    key = get_encryption_key()
    if not key:
        raise ValueError(
            "OPENRAG_ENCRYPTION_KEY not found in environment, but encrypted secret detected in config."
        )

    try:
        aesgcm = AESGCM(key)
        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        
        tenant_id = payload.get("tenant_id", "openrag")
        aad = f"tenant_id:{tenant_id}".encode("utf-8")

        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, aad)
        return plaintext_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to decrypt secret: {e}")
        raise ValueError(f"Failed to decrypt secret: {e}")

async def read_encrypted_file(file_path: str) -> Tuple[Optional[str], bool]:
    """
    Reads an encrypted or plaintext JSON/string file.
    Returns a tuple: (file_content_as_string, needs_upgrade_boolean)
    """
    if not os.path.exists(file_path):
        return None, False
        
    try:
        async with aiofiles.open(file_path, "r") as f:
            raw_data = await f.read()

        if not raw_data.strip():
            return raw_data, False

        file_json = json.loads(raw_data)
        if isinstance(file_json, dict) and file_json.get("algorithm") == "AES-256-GCM":
            decrypted_str = decrypt_secret(file_json)
            return decrypted_str, False
        else:
            # It's plaintext
            needs_upgrade = get_encryption_key() is not None
            return raw_data, needs_upgrade
    except json.JSONDecodeError:
        # Not a JSON dict, could be MSAL plaintext string or something else
        needs_upgrade = get_encryption_key() is not None
        return raw_data, needs_upgrade
    except Exception as e:
        logger.error(f"Failed to read encrypted file {file_path}: {e}")
        return None, False

async def write_encrypted_file(file_path: str, data: str):
    """
    Encrypts string data (if key is present) and writes to file.
    """
    encrypted = encrypt_secret(data)
    payload_to_write = json.dumps(encrypted, indent=2) if isinstance(encrypted, dict) else data

    # Ensure parent dir exists
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    async with aiofiles.open(file_path, "w") as f:
        await f.write(payload_to_write)

