import os
import sys
import base64
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set fake encryption key
os.environ["OPENRAG_ENCRYPTION_KEY"] = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")

from utils.encryption import encrypt_secret, decrypt_secret
from config.config_manager import ConfigManager
from connectors.connection_manager import ConnectionManager

import asyncio

def test_encryption_utility():
    print("Testing encryption utility...")
    plaintext = "super-secret-api-key"
    payload = encrypt_secret(plaintext, "tenant-1")
    assert isinstance(payload, dict)
    assert payload["algorithm"] == "AES-256-GCM"
    assert payload["tenant_id"] == "tenant-1"
    
    decrypted = decrypt_secret(payload)
    assert decrypted == plaintext
    print("OK")

def test_config_manager():
    print("Testing config manager encryption...")
    # Create an initial config manager with a temporary file
    test_yaml = Path("/tmp/test_openrag_config.yaml")
    if test_yaml.exists():
        test_yaml.unlink()
        
    cm = ConfigManager(str(test_yaml))
    config = cm.get_config()
    config.providers.openai.api_key = "openai-api-key-plaintext"
    
    # Save the config
    cm.save_config_file(config)
    
    import yaml
    with open(test_yaml, "r") as f:
        saved_data = yaml.safe_load(f)
        
    # Verify it was encrypted on disk
    assert isinstance(saved_data["providers"]["openai"]["api_key"], dict)
    assert saved_data["providers"]["openai"]["api_key"]["algorithm"] == "AES-256-GCM"
    
    # Verify it can be loaded correctly
    cm_new = ConfigManager(str(test_yaml))
    config_new = cm_new.get_config()
    assert config_new.providers.openai.api_key == "openai-api-key-plaintext"
    print("OK")

def test_connection_manager():
    print("Testing connection manager encryption...")
    test_json = Path("/tmp/test_openrag_connections.json")
    if test_json.exists():
        test_json.unlink()
        
    async def run():
        cm = ConnectionManager(str(test_json))
        await cm.create_connection(
            connector_type="google_drive",
            name="Test Drive",
            config={"client_secret": "my-client-secret-plaintext", "other_setting": "not-secret"},
            user_id="user-1"
        )
        # Should be saved encrypted
        import json
        with open(test_json, "r") as f:
            data = json.load(f)
            
        found = False
        for c in data["connections"]:
            if c["connector_type"] == "google_drive":
                found = True
                assert isinstance(c["config"]["client_secret"], dict)
                assert c["config"]["client_secret"]["algorithm"] == "AES-256-GCM"
                assert c["config"]["other_setting"] == "not-secret"
        assert found
        
        # Reloading should decrypt
        cm2 = ConnectionManager(str(test_json))
        await cm2.load_connections()
        
        found = False
        for c in cm2.connections.values():
            if c.connector_type == "google_drive":
                found = True
                assert c.config["client_secret"] == "my-client-secret-plaintext"
                assert c.config["other_setting"] == "not-secret"
        assert found
        print("OK")
        
    asyncio.run(run())

    print("Testing auto-upgrade features...")
    test_yaml = Path("/tmp/test_openrag_config_upgrade.yaml")
    import yaml
    # Write purely plaintext config
    with open(test_yaml, "w") as f:
        yaml.dump({
            "providers": {
                "openai": {"api_key": "raw-unencrypted-openai-key-from-past"}
            }
        }, f)
        
    cm = ConfigManager(str(test_yaml))
    cm.get_config()
    # Upon loading, the auto-upgrade should save the file over itself with the encrypted key.
    with open(test_yaml, "r") as f:
        upgraded_data = yaml.safe_load(f)
    assert isinstance(upgraded_data["providers"]["openai"]["api_key"], dict), "Failed to auto-upgrade config"
    assert upgraded_data["providers"]["openai"]["api_key"]["algorithm"] == "AES-256-GCM"
    assert cm.get_config().providers.openai.api_key == "raw-unencrypted-openai-key-from-past"
    print("Auto-upgrade OK")
    
if __name__ == "__main__":
    test_encryption_utility()
    test_config_manager()
    test_connection_manager()
    print("All tests passed!")
