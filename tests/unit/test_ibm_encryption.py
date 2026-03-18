import base64

import pytest

from utils import encryption

@pytest.fixture
def run_env(monkeypatch):
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", base64.b64encode(b"B" * 32).decode("ascii"))
    monkeypatch.delenv("IBM_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("IBM_CLOUD_TRUSTED_PROFILE_ID", raising=False)
    monkeypatch.setattr(encryption, "_cached_master_secret", None)
    return monkeypatch

def test_fallback_when_credentials_missing(run_env):
    # No IBM keys set here
    key = encryption.get_master_secret()
    assert key == base64.b64encode(b"B" * 32).decode("ascii")
    print("Fallback with missing IBM creds successful")

def test_cache_mechanism(run_env):
    k1 = encryption.get_master_secret()
    assert encryption._cached_master_secret is not None
    
    # Remove local env ensuring it hits cache
    run_env.delenv("OPENRAG_ENCRYPTION_KEY", raising=False)
    k2 = encryption.get_master_secret()
    assert k2 == k1
    print("Caching optimization successful")

def test_ibm_exception_handling(run_env):
    run_env.setenv("IBM_AUTH_ENABLED", "true")
    run_env.setenv("IBM_CLOUD_API_KEY", "fake")
    run_env.setenv("SECRET_MANAGER_INSTANCE_ID", "fake")
    run_env.setenv("IBM_SECRETS_MANAGER_SECRET_ID", "fake")
    run_env.setenv("OPENRAG_ENCRYPTION_KEY", base64.b64encode(b"C" * 32).decode("ascii"))
    
    from unittest.mock import patch
    with patch("ibm_secrets_manager_sdk.secrets_manager_v2.SecretsManagerV2", side_effect=ValueError("Simulating SDK crash")):
        key = encryption.get_master_secret()
        assert key == base64.b64encode(b"C" * 32).decode("ascii")
        print("IBM SDK exception intercept successful")

def test_trusted_profiles_fallback(run_env):
    run_env.delenv("IBM_CLOUD_API_KEY", raising=False)
        
    run_env.setenv("IBM_AUTH_ENABLED", "true")
    run_env.setenv("SECRET_MANAGER_INSTANCE_ID", "fake")
    run_env.setenv("IBM_SECRETS_MANAGER_SECRET_ID", "fake")
    run_env.setenv("IBM_CLOUD_TRUSTED_PROFILE_ID", "my-profile")
    run_env.setenv("SECRET_MANAGER_REGION", "us-east")
    run_env.setenv("OPENRAG_ENCRYPTION_KEY", base64.b64encode(b"D" * 32).decode("ascii"))
    
    from unittest.mock import patch
    with patch("ibm_secrets_manager_sdk.secrets_manager_v2.SecretsManagerV2", side_effect=ValueError("Simulating SDK crash")):
        key = encryption.get_master_secret()
        assert key == base64.b64encode(b"D" * 32).decode("ascii")
        print("Trusted Profile exception intercept successful")

