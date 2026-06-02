"""RSA keypair generation for JWT signing."""

import os
import subprocess

from config.paths import get_keys_path
from utils.logging_config import get_logger
from utils.telemetry import Category, MessageId, TelemetryClient

logger = get_logger(__name__)


def generate_jwt_keys():
    """Generate RSA keys for JWT signing if they don't exist"""
    keys_dir = get_keys_path()
    private_key_path = os.path.join(keys_dir, "private_key.pem")
    public_key_path = os.path.join(keys_dir, "public_key.pem")

    os.makedirs(keys_dir, exist_ok=True)

    if not os.path.exists(private_key_path):
        try:
            subprocess.run(
                ["openssl", "genrsa", "-out", private_key_path, "2048"],
                check=True,
                capture_output=True,
            )

            os.chmod(private_key_path, 0o600)

            subprocess.run(
                [
                    "openssl",
                    "rsa",
                    "-in",
                    private_key_path,
                    "-pubout",
                    "-out",
                    public_key_path,
                ],
                check=True,
                capture_output=True,
            )

            os.chmod(public_key_path, 0o644)

            logger.info("Generated RSA keys for JWT signing")
        except subprocess.CalledProcessError as e:
            logger.error("Failed to generate RSA keys", error=str(e))
            TelemetryClient.send_event_sync(
                Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_JWT_KEY_FAIL
            )
            raise
    else:
        logger.info("RSA keys already exist")
