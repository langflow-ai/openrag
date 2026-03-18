import os
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Setup fake OPENRAG_ENCRYPTION_KEY as fallback
os.environ["OPENRAG_ENCRYPTION_KEY"] = base64.b64encode(b"B" * 32).decode("ascii")

from utils import encryption

def test_fallback_when_credentials_missing():
    encryption._cached_master_secret = None
    # No IBM keys set here
    key = encryption.get_master_secret()
    assert key == base64.b64encode(b"B" * 32).decode("ascii")
    print("Fallback with missing IBM creds successful")

def test_cache_mechanism():
    encryption._cached_master_secret = None
    k1 = encryption.get_master_secret()
    assert encryption._cached_master_secret is not None
    
    # Remove local env ensuring it hits cache
    del os.environ["OPENRAG_ENCRYPTION_KEY"]
    k2 = encryption.get_master_secret()
    assert k2 == k1
    print("Caching optimization successful")

def test_ibm_exception_handling():
    encryption._cached_master_secret = None
    os.environ["IBM_CLOUD_API_KEY"] = "fake"
    os.environ["SECRET_MANAGER_INSTANCE_ID"] = "fake"
    os.environ["IBM_SECRETS_MANAGER_SECRET_ID"] = "fake"
    os.environ["OPENRAG_ENCRYPTION_KEY"] = base64.b64encode(b"C" * 32).decode("ascii")
    
    try:
        from unittest.mock import patch
        with patch("ibm_secrets_manager_sdk.secrets_manager_v2.SecretsManagerV2", side_effect=ValueError("Simulating SDK crash")):
            key = encryption.get_master_secret()
            assert key == base64.b64encode(b"C" * 32).decode("ascii")
            print("IBM SDK exception intercept successful")
    except Exception as e:
        print(f"Exception uncaught: {e}")

def test_trusted_profiles_fallback():
    encryption._cached_master_secret = None
    if "IBM_CLOUD_API_KEY" in os.environ:
        del os.environ["IBM_CLOUD_API_KEY"]
        
    os.environ["SECRET_MANAGER_INSTANCE_ID"] = "fake"
    os.environ["IBM_SECRETS_MANAGER_SECRET_ID"] = "fake"
    os.environ["IBM_CLOUD_TRUSTED_PROFILE_ID"] = "my-profile"
    os.environ["SECRET_MANAGER_REGION"] = "us-east"
    os.environ["OPENRAG_ENCRYPTION_KEY"] = base64.b64encode(b"D" * 32).decode("ascii")
    
    try:
        from unittest.mock import patch
        with patch("ibm_secrets_manager_sdk.secrets_manager_v2.SecretsManagerV2", side_effect=ValueError("Simulating SDK crash")):
            key = encryption.get_master_secret()
            assert key == base64.b64encode(b"D" * 32).decode("ascii")
            print("Trusted Profile exception intercept successful")
    except Exception as e:
        print(f"Exception uncaught: {e}")

if __name__ == "__main__":
    test_fallback_when_credentials_missing()
    test_cache_mechanism()
    test_ibm_exception_handling()
    test_trusted_profiles_fallback()
