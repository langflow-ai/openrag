import os
import secrets
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Union, Dict, Any, Tuple, Optional
import aiofiles
import json
from utils.logging_config import get_logger

logger = get_logger(__name__)

# KDF Constants
ENCRYPTION_ALGORITHM = "AES-256-GCM"
KDF_ALGORITHM = hashes.SHA256()
KDF_ITERATIONS = 100000

_cached_master_secret: Optional[str] = None

def get_master_secret() -> str | None:
    """Retrieve the master secret string from IBM Secrets Manager or local environment."""
    global _cached_master_secret
    if _cached_master_secret is not None:
        return _cached_master_secret

    secret_str = None
    ibm_auth_enabled = os.environ.get("IBM_AUTH_ENABLED", "false").lower() in ("true", "1", "yes")

    if ibm_auth_enabled:
        ibm_api_key = os.environ.get("IBM_CLOUD_API_KEY")
        ibm_secret_id = os.environ.get("IBM_SECRETS_MANAGER_SECRET_ID")
        
        trusted_profile_id = os.environ.get("IBM_CLOUD_TRUSTED_PROFILE_ID")
        instance_id = os.environ.get("SECRET_MANAGER_INSTANCE_ID")
        region = os.environ.get("SECRET_MANAGER_REGION", "us-south")
        cr_token_file = os.environ.get("IBM_CLOUD_CR_TOKEN_FILE", "/var/run/secrets/tokens/sa-token")

        if instance_id and ibm_secret_id:
            try:
                from ibm_secrets_manager_sdk.secrets_manager_v2 import SecretsManagerV2
                
                authenticator = None
                if ibm_api_key:
                    from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
                    authenticator = IAMAuthenticator(ibm_api_key)
                elif trusted_profile_id:
                    from ibm_cloud_sdk_core.authenticators import ContainerAuthenticator
                    authenticator = ContainerAuthenticator(
                        cr_token_filename=cr_token_file,
                        iam_profile_id=trusted_profile_id
                    )
                else:
                    raise ValueError("Neither IBM_CLOUD_API_KEY nor IBM_CLOUD_TRUSTED_PROFILE_ID provided")

                secrets_manager = SecretsManagerV2(authenticator=authenticator)
                secrets_manager.set_service_url(f"https://{instance_id}.{region}.secrets-manager.appdomain.cloud")

                # Retrieve the secret
                response = secrets_manager.get_secret(id=ibm_secret_id).get_result()
                
                secret_data = response.get("secret_data")
                if not secret_data and "resources" in response and len(response["resources"]) > 0:
                    secret_data = response["resources"][0].get("secret_data")
                    
                if secret_data and "payload" in secret_data:
                    secret_str = secret_data["payload"]
                    logger.debug("Successfully retrieved master secret from IBM Secrets Manager.")
                else:
                    logger.warning("IBM Secrets Manager: 'payload' not found in secret_data.")
            except Exception as e:
                logger.warning(f"Failed to retrieve encryption key from IBM Secrets Manager: {e}. Falling back to OPENRAG_ENCRYPTION_KEY.")

    if not secret_str:
        secret_str = os.environ.get("OPENRAG_ENCRYPTION_KEY")

    if not secret_str:
        if os.environ.get("OPENRAG_ENFORCE_PREREQUISITES", "false").lower() in ("true", "1", "yes"):
            raise RuntimeError(
                "CRITICAL: OPENRAG_ENFORCE_PREREQUISITES is enabled but no master encryption key "
                "could be retrieved from IBM Secrets Manager or OPENRAG_ENCRYPTION_KEY. "
                "Application will not start in unencrypted mode."
            )
        return None

    _cached_master_secret = secret_str
    return secret_str


def enforce_startup_prerequisites():
    """
    Validates that the encryption master secret is available if ENFORCE_PREREQUISITES is set.
    This should be called early during application startup.
    """
    try:
        get_master_secret()
    except RuntimeError as e:
        logger.critical(str(e))
        import sys
        sys.exit(1)



def encrypt_secret(plaintext: str, tenant_id: str = "openrag") -> Union[Dict[str, Any], str]:
    """
    Encrypt a plaintext secret using AES-256-GCM and PBKDF2HMAC.
    Returns a JSON-serializable dictionary with the ciphertext and metadata.
    If master secret is not set, returns the plaintext string for backward compatibility.
    """
    if not isinstance(plaintext, str) or not plaintext:
        return plaintext

    master_secret = get_master_secret()
    if not master_secret:
        return plaintext

    try:
        salt = secrets.token_bytes(16)
        kdf = PBKDF2HMAC(
            algorithm=KDF_ALGORITHM,
            length=32,
            salt=salt,
            iterations=KDF_ITERATIONS,
        )
        derived_key = kdf.derive(master_secret.encode("utf-8"))

        aesgcm = AESGCM(derived_key)
        nonce = secrets.token_bytes(12)
        plaintext_bytes = plaintext.encode("utf-8")
        aad = f"tenant_id:{tenant_id}".encode("utf-8")

        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, aad)

        return {
            "version": "1.0",
            "algorithm": ENCRYPTION_ALGORITHM,
            "kdf": "PBKDF2HMAC-SHA256",
            "tenant_id": tenant_id,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
    except Exception as e:
        logger.error(f"Failed to encrypt secret: {e}")
        # If encryption fails, fallback to plaintext so we don't lose data
        return plaintext


def decrypt_secret(payload: Union[Dict[str, Any], str], expected_tenant_id: Optional[str] = None) -> str:
    """
    Decrypt a secret payload using AES-256-GCM.
    Supports backward compatibility with non-KDF base64 raw keys.
    If expected_tenant_id is provided, it is used as the authoritative tenant identifier 
    for constructing the AES-GCM AAD, and the payload's tenant_id (if present) must match it.
    """
    if not isinstance(payload, dict):
        return payload

    if payload.get("algorithm") != ENCRYPTION_ALGORITHM or "ciphertext" not in payload:
        raise ValueError(
            "Invalid encrypted secret payload: expected AES-256-GCM envelope with 'algorithm' "
            "set to 'AES-256-GCM' and a 'ciphertext' field."
        )

    master_secret = get_master_secret()
    if not master_secret:
        raise ValueError(
            "Master secret not found in environment, but encrypted secret detected in config."
        )

    try:
        # Backward compatibility for originally raw base64 32-byte keys
        if "salt" in payload:
            salt = base64.b64decode(payload["salt"])
            kdf = PBKDF2HMAC(
                algorithm=KDF_ALGORITHM,
                length=32,
                salt=salt,
                iterations=KDF_ITERATIONS,
            )
            key = kdf.derive(master_secret.encode("utf-8"))
        else:
            # Legacy assumption: master_secret was exactly 32 bytes of raw base64 data
            key = base64.b64decode(master_secret)

        aesgcm = AESGCM(key)
        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        
        # Determine tenant_id for AAD using a trusted expected value when available.
        payload_tenant_id = payload.get("tenant_id")
        if expected_tenant_id is not None:
            if payload_tenant_id is not None and payload_tenant_id != expected_tenant_id:
                raise ValueError(
                    f"Tenant ID in payload ('{payload_tenant_id}') does not match expected tenant ID."
                )
            tenant_id = expected_tenant_id
        else:
            # Backwards-compatible behaviour when no external tenant binding is configured.
            tenant_id = payload_tenant_id or "openrag"
            
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
        if isinstance(file_json, dict) and file_json.get("algorithm") == ENCRYPTION_ALGORITHM:
            expected_tenant_id = os.getenv("OPENRAG_TENANT_ID")
            decrypted_str = decrypt_secret(file_json, expected_tenant_id=expected_tenant_id)
            return decrypted_str, False
        else:
            # It's plaintext
            needs_upgrade = get_master_secret() is not None
            return raw_data, needs_upgrade
    except json.JSONDecodeError:
        # Not a JSON dict, could be MSAL plaintext string or something else
        needs_upgrade = get_master_secret() is not None
        return raw_data, needs_upgrade
    except Exception as e:
        logger.error(f"Failed to read encrypted file {file_path}: {e}")
        return None, False

async def write_encrypted_file(file_path: str, data: str):
    """
    Encrypts string data (if key is present) and writes to file.
    """
    tenant_id = os.getenv("OPENRAG_TENANT_ID") or "openrag"
    encrypted = encrypt_secret(data, tenant_id=tenant_id)
    payload_to_write = json.dumps(encrypted, indent=2) if isinstance(encrypted, dict) else data

    # Ensure parent dir exists
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    async with aiofiles.open(file_path, "w") as f:
        await f.write(payload_to_write)

