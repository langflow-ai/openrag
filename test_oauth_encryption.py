import os
import sys
import base64
from pathlib import Path
import json
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ["OPENRAG_ENCRYPTION_KEY"] = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")

from connectors.google_drive.oauth import GoogleDriveOAuth
from connectors.onedrive.oauth import OneDriveOAuth

async def run_tests():
    print("Testing Google Drive Auth Upgrade...")
    g_token_path = "/tmp/fake_gdrive_token.json"
    g_plain = {
        "token": "fake-google-token",
        "refresh_token": "fake-refresh",
        "scopes": ["some-scope"],
        "expiry": "2026-03-02T15:46:11.368083"
    }
    with open(g_token_path, "w") as f:
        json.dump(g_plain, f)
        
    g_oauth = GoogleDriveOAuth(client_id="abc", client_secret="def", token_file=g_token_path)
    try:
        creds = await g_oauth.load_credentials()
    except ValueError:
        print("Expected network validation error caught. Proceeding to verify disk encryption...")
        pass
    
    # Check if upgraded
    with open(g_token_path, "r") as f:
        upgraded = json.load(f)
    assert "algorithm" in upgraded and upgraded["algorithm"] == "AES-256-GCM"
    print("Google Drive Auth OK")

    print("Testing MSAL Auth Upgrade...")
    m_token_path = "/tmp/fake_msal_token.json"
    m_plain = {
        "refresh_token": "legacy-flat-refresh-token"
    }
    with open(m_token_path, "w") as f:
        json.dump(m_plain, f)
        
    m_oauth = OneDriveOAuth(client_id="abc", client_secret="def", token_file=m_token_path)
    
    # We monkey patch MSAL acquire_token_by_refresh_token to pretend it worked
    m_oauth.app.acquire_token_by_refresh_token = lambda refresh_token, scopes: {"access_token": "new-access-token"}
    m_oauth.app.get_accounts = lambda: [{"username": "fake-user"}]
    
    result = await m_oauth.load_credentials()
    assert result
    
    with open(m_token_path, "r") as f:
        upgraded_m = json.load(f)
    assert "algorithm" in upgraded_m and upgraded_m["algorithm"] == "AES-256-GCM"
    print("MSAL Auth OK")

if __name__ == "__main__":
    asyncio.run(run_tests())
