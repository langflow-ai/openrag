import json

import pytest
from connectors.google_drive.oauth import GoogleDriveOAuth
from connectors.onedrive.oauth import OneDriveOAuth

@pytest.mark.asyncio
async def test_google_drive_auth_upgrade(tmp_path, monkeypatch):
    """Test that Google Drive credentials are encrypted on load if not already."""
    import utils.encryption
    # Reset internal cache to ensure it reads from env
    utils.encryption._cached_master_secret = None
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "dGVzdC1rZXktMzItYnl0ZXMtZm9yLXVuaXQtdGVzdGluZy1vbmx5") # 32-byte base64

    print("Testing Google Drive Auth Upgrade...")
    g_token_path = tmp_path / "fake_gdrive_token.json"
    g_plain = {
        "token": "fake-google-token",
        "refresh_token": "fake-refresh",
        "scopes": ["some-scope"],
        "expiry": "2028-03-02T15:46:11.368083"
    }
    with open(g_token_path, "w") as f:
        json.dump(g_plain, f)
        
    g_oauth = GoogleDriveOAuth(client_id="abc", client_secret="def", token_file=str(g_token_path))
    try:
        await g_oauth.load_credentials()
    except ValueError:
        print("Expected network validation error caught. Proceeding to verify disk encryption...")
    
    # Check if upgraded
    with open(g_token_path, "r") as f:
        upgraded = json.load(f)
    assert "algorithm" in upgraded and upgraded["algorithm"] == "AES-256-GCM"
    print("Google Drive Auth OK")

@pytest.mark.asyncio
async def test_msal_auth_upgrade(tmp_path, monkeypatch):
    """Test that MSAL credentials are encrypted on load if not already."""
    import utils.encryption
    # Reset internal cache to ensure it reads from env
    utils.encryption._cached_master_secret = None
    monkeypatch.setenv("OPENRAG_ENCRYPTION_KEY", "dGVzdC1rZXktMzItYnl0ZXMtZm9yLXVuaXQtdGVzdGluZy1vbmx5") # 32-byte base64

    print("Testing MSAL Auth Upgrade...")
    m_token_path = tmp_path / "fake_msal_token.json"
    m_plain = {
        "refresh_token": "legacy-flat-refresh-token"
    }
    with open(m_token_path, "w") as f:
        json.dump(m_plain, f)
        
    m_oauth = OneDriveOAuth(client_id="abc", client_secret="def", token_file=str(m_token_path))
    
    # We monkey patch MSAL acquire_token_by_refresh_token to pretend it worked
    m_oauth.app.acquire_token_by_refresh_token = lambda refresh_token, scopes: {"access_token": "new-access-token"}
    m_oauth.app.get_accounts = lambda: [{"username": "fake-user"}]
    
    result = await m_oauth.load_credentials()
    assert result
    
    with open(m_token_path, "r") as f:
        upgraded_m = json.load(f)
    assert "algorithm" in upgraded_m and upgraded_m["algorithm"] == "AES-256-GCM"
    print("MSAL Auth OK")
