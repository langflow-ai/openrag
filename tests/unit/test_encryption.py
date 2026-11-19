import base64

import pytest

from config.config_manager import ConfigManager
from connectors.connection_manager import ConnectionManager
from utils.encryption import decrypt_secret, encrypt_secret


@pytest.fixture(autouse=True)
def setup_encryption_env(monkeypatch):
    import utils.encryption

    utils.encryption._cached_master_secret = None
    monkeypatch.setenv(
        "OPENRAG_ENCRYPTION_KEY",
        base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii"),
    )


def test_encryption_utility():
    print("Testing encryption utility...")
    plaintext = "super-secret-api-key"
    payload = encrypt_secret(plaintext, "tenant-1")
    assert isinstance(payload, dict)
    assert payload["algorithm"] == "AES-256-GCM"
    assert payload["tenant_id"] == "tenant-1"

    # Passing explicitly matches original AAD
    decrypted = decrypt_secret(payload, expected_tenant_id="tenant-1")
    assert decrypted == plaintext

    # Missing explicit bound works generically using payload lookup
    decrypted_fallback = decrypt_secret(payload)
    assert decrypted_fallback == plaintext

    # Spoofing the identity dynamically rejects the AES-GCM tags!
    with pytest.raises(ValueError):
        decrypt_secret(payload, expected_tenant_id="wrong-tenant-id")
    print("OK")


def test_config_manager(tmp_path):
    print("Testing config manager encryption...")
    # Create an initial config manager with a temporary file
    test_yaml = tmp_path / "test_openrag_config.yaml"
    if test_yaml.exists():
        test_yaml.unlink()

    cm = ConfigManager(str(test_yaml))
    config = cm.get_config()
    config.providers.openai.api_key = "openai-api-key-plaintext"

    # Save the config
    cm.save_config_file(config)

    import yaml

    with open(test_yaml) as f:
        saved_data = yaml.safe_load(f)

    # Verify it was encrypted on disk
    assert isinstance(saved_data["providers"]["openai"]["api_key"], dict)
    assert saved_data["providers"]["openai"]["api_key"]["algorithm"] == "AES-256-GCM"

    # Verify it can be loaded correctly
    cm_new = ConfigManager(str(test_yaml))
    config_new = cm_new.get_config()
    assert config_new.providers.openai.api_key == "openai-api-key-plaintext"
    print("OK")


@pytest.mark.asyncio
async def test_connection_manager(tmp_path):
    print("Testing connection manager encryption...")
    test_json = tmp_path / "test_openrag_connections.json"
    if test_json.exists():
        test_json.unlink()

    cm = ConnectionManager(str(test_json))
    await cm.create_connection(
        connector_type="google_drive",
        name="Test Drive",
        config={"client_secret": "my-client-secret-plaintext", "other_setting": "not-secret"},
        user_id="user-1",
    )
    await cm.create_connection(
        connector_type="aws_s3",
        name="Test S3",
        config={"secret_key": "aws-secret", "access_key": "aws-access", "bucket_names": ["foo"]},
        user_id="user-1",
    )
    await cm.create_connection(
        connector_type="ibm_cos",
        name="Test IBM",
        config={
            "api_key": "ibm-api-key",
            "service_instance_id": "ibm-service",
            "bucket_names": ["bar"],
        },
        user_id="user-1",
    )
    # Should be saved encrypted
    import json

    with open(test_json) as f:
        data = json.load(f)

    found_gd = False
    found_s3 = False
    found_ibm = False
    for c in data["connections"]:
        if c["connector_type"] == "google_drive":
            found_gd = True
            assert isinstance(c["config"]["client_secret"], dict)
            assert c["config"]["client_secret"]["algorithm"] == "AES-256-GCM"
            assert c["config"]["other_setting"] == "not-secret"
        if c["connector_type"] == "aws_s3":
            found_s3 = True
            assert isinstance(c["config"]["secret_key"], dict)
            assert c["config"]["secret_key"]["algorithm"] == "AES-256-GCM"
            assert isinstance(c["config"]["access_key"], dict)
            assert c["config"]["bucket_names"] == ["foo"]
        if c["connector_type"] == "ibm_cos":
            found_ibm = True
            assert isinstance(c["config"]["api_key"], dict)
            assert c["config"]["api_key"]["algorithm"] == "AES-256-GCM"
            assert isinstance(c["config"]["service_instance_id"], dict)
    assert found_gd and found_s3 and found_ibm

    # Reloading should decrypt
    cm2 = ConnectionManager(str(test_json))
    await cm2.load_connections()

    found_gd = False
    found_s3 = False
    found_ibm = False
    for c in cm2.connections.values():
        if c.connector_type == "google_drive":
            found_gd = True
            assert c.config["client_secret"] == "my-client-secret-plaintext"
            assert c.config["other_setting"] == "not-secret"
        elif c.connector_type == "aws_s3":
            found_s3 = True
            assert c.config["secret_key"] == "aws-secret"
            assert c.config["access_key"] == "aws-access"
        elif c.connector_type == "ibm_cos":
            found_ibm = True
            assert c.config["api_key"] == "ibm-api-key"
            assert c.config["service_instance_id"] == "ibm-service"
    assert found_gd and found_s3 and found_ibm
    print("OK")


def test_auto_upgrade_features(tmp_path, monkeypatch):
    # A developer's OPENAI_API_KEY would seed the config and mask the file value.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    test_yaml = tmp_path / "test_openrag_config_upgrade.yaml"
    import yaml

    # Write purely plaintext config
    with open(test_yaml, "w") as f:
        yaml.dump({"providers": {"openai": {"api_key": "raw-unencrypted-openai-key-from-past"}}}, f)

    cm = ConfigManager(str(test_yaml))
    cm.get_config()
    # Upon loading, the auto-upgrade should save the file over itself with the encrypted key.
    with open(test_yaml) as f:
        upgraded_data = yaml.safe_load(f)
    assert isinstance(upgraded_data["providers"]["openai"]["api_key"], dict), (
        "Failed to auto-upgrade config"
    )
    assert upgraded_data["providers"]["openai"]["api_key"]["algorithm"] == "AES-256-GCM"
    assert cm.get_config().providers.openai.api_key == "raw-unencrypted-openai-key-from-past"
    print("Auto-upgrade OK")


@pytest.mark.asyncio
async def test_ibm_credentials_round_trip_decrypts(tmp_path):
    """ibm_credentials has no connector class; its known secret must still decrypt."""
    import json

    path = tmp_path / "connections.json"
    writer = ConnectionManager(str(path))
    await writer.upsert_ibm_credentials("u1", "Basic abc", "alice")
    stored = json.loads(path.read_text())["connections"][0]["config"]
    assert stored["basic_credentials"]["algorithm"] == "AES-256-GCM"

    reader = ConnectionManager(str(path))
    await reader.load_connections()
    (conn,) = await reader.list_connections(user_id="u1", connector_type="ibm_credentials")
    assert conn.config["basic_credentials"] == "Basic abc"


@pytest.mark.asyncio
async def test_malformed_record_is_quarantined_and_preserved(tmp_path):
    """A bad record must not abort the load or be dropped by the next save."""
    import json

    path = tmp_path / "connections.json"
    malformed = {
        "connection_id": "bad-1",
        "connector_type": "google_drive",
        "name": "Broken",
        "config": {},
        "user_id": "u1",
        "created_at": "not-a-date",
    }
    good = {
        "connection_id": "good-1",
        "connector_type": "google_drive",
        "name": "Drive",
        "config": {"other_setting": "x"},
        "user_id": "u1",
        "created_at": "2026-01-01T00:00:00",
    }
    path.write_text(json.dumps({"connections": [malformed, good]}))

    cm = ConnectionManager(str(path))
    await cm.load_connections()
    assert set(cm.connections) == {"good-1"}

    await cm.create_connection(
        connector_type="aws_s3", name="S3", config={"bucket_names": ["b"]}, user_id="u2"
    )
    saved = json.loads(path.read_text())["connections"]
    assert malformed in saved
    assert {c["connection_id"] for c in saved} >= {"bad-1", "good-1"}
    assert len(saved) == 3
