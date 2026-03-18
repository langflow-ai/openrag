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

_cached_master_secret: Optional[str] = None

def get_master_secret() -> str | None:
    """Retrieve the master secret string from IBM Secrets Manager or local environment."""
    global _cached_master_secret
    if _cached_master_secret is not None:
        return _cached_master_secret

    secret_str = None

    ibm_api_key = os.environ.get("IBM_CLOUD_API_KEY")
    ibm_url = os.environ.get("IBM_SECRETS_MANAGER_URL")
    ibm_secret_id = os.environ.get("IBM_SECRETS_MANAGER_SECRET_ID")
    ibm_profile_crn = os.environ.get("IBM_IAM_PROFILE_CRN")
    ibm_profile_name = os.environ.get("IBM_IAM_PROFILE_NAME")

    if ibm_url and ibm_secret_id:
        try:
            from ibm_secrets_manager_sdk.secrets_manager_v2 import SecretsManagerV2
            
            authenticator = None
            if ibm_api_key:
                from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
                authenticator = IAMAuthenticator(ibm_api_key)
            else:
                from ibm_cloud_sdk_core.authenticators import ContainerAuthenticator
                kwargs = {}
                if ibm_profile_crn:
                    kwargs["iam_profile_crn"] = ibm_profile_crn
                if ibm_profile_name:
                    kwargs["iam_profile_name"] = ibm_profile_name
                if os.environ.get("IBM_IAM_PROFILE_ID"):
                    kwargs["iam_profile_id"] = os.environ.get("IBM_IAM_PROFILE_ID")
                
                authenticator = ContainerAuthenticator(**kwargs)

            secrets_manager = SecretsManagerV2(authenticator=authenticator)
            secrets_manager.set_service_url(ibm_url)

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
        return None

    _cached_master_secret = secret_str
    return secret_str



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
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        derived_key = kdf.derive(master_secret.encode("utf-8"))

        aesgcm = AESGCM(derived_key)
        nonce = secrets.token_bytes(12)
        plaintext_bytes = plaintext.encode("utf-8")
        aad = f"tenant_id:{tenant_id}".encode("utf-8")

        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, aad)

        return {
            "version": "1.0",
            "algorithm": "AES-256-GCM",
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


def decrypt_secret(payload: Union[Dict[str, Any], str]) -> str:
    """
    Decrypt a secret payload using AES-256-GCM.
    Supports backward compatibility with non-KDF base64 raw keys.
    """
    if not isinstance(payload, dict):
        return payload

    if payload.get("algorithm") != "AES-256-GCM" or "ciphertext" not in payload:
        return payload

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
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = kdf.derive(master_secret.encode("utf-8"))
        else:
            # Legacy assumption: master_secret was exactly 32 bytes of raw base64 data
            key = base64.b64decode(master_secret)

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
    encrypted = encrypt_secret(data)
    payload_to_write = json.dumps(encrypted, indent=2) if isinstance(encrypted, dict) else data

    # Ensure parent dir exists
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    async with aiofiles.open(file_path, "w") as f:
        await f.write(payload_to_write)

