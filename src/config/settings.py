import os
import requests
import asyncio
import time
from dotenv import load_dotenv
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection
from docling.document_converter import DocumentConverter
from agentd.patch import patch_openai_with_mcp
from openai import AsyncOpenAI

load_dotenv()
load_dotenv("../")

# Environment variables
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USERNAME = os.getenv("OPENSEARCH_USERNAME", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD")
LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://localhost:7860")
# Optional: public URL for browser links (e.g., http://localhost:7860)
LANGFLOW_PUBLIC_URL = os.getenv("LANGFLOW_PUBLIC_URL")
FLOW_ID = os.getenv("FLOW_ID")
# Langflow superuser credentials for API key generation
LANGFLOW_SUPERUSER = os.getenv("LANGFLOW_SUPERUSER")
LANGFLOW_SUPERUSER_PASSWORD = os.getenv("LANGFLOW_SUPERUSER_PASSWORD")
# Allow explicit key via environment; generation will be skipped if set
LANGFLOW_KEY = os.getenv("LANGFLOW_KEY")
SESSION_SECRET = os.getenv("SESSION_SECRET", "your-secret-key-change-in-production")
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

def is_no_auth_mode():
    """Check if we're running in no-auth mode (OAuth credentials missing)"""
    result = not (GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)
    print(f"[DEBUG] is_no_auth_mode() = {result}, CLIENT_ID={GOOGLE_OAUTH_CLIENT_ID is not None}, CLIENT_SECRET={GOOGLE_OAUTH_CLIENT_SECRET is not None}")
    return result

# Webhook configuration - must be set to enable webhooks
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")  # No default - must be explicitly configured

# OpenSearch configuration
INDEX_NAME = "documents"
VECTOR_DIM = 1536
EMBED_MODEL = "text-embedding-3-small"

INDEX_BODY = {
    "settings": {
        "index": {"knn": True},
        "number_of_shards": 1,
        "number_of_replicas": 1
    },
    "mappings": {
        "properties": {
            "document_id": { "type": "keyword" },
            "filename":    { "type": "keyword" },
            "mimetype":    { "type": "keyword" },
            "page":        { "type": "integer" },
            "text":        { "type": "text" },
            "chunk_embedding": {
                "type": "knn_vector",
                "dimension": VECTOR_DIM,
                "method": {
                    "name":       "disk_ann",
                    "engine":     "jvector",
                    "space_type": "l2",
                    "parameters": {
                        "ef_construction": 100,
                        "m":               16
                    }
                }
            },
            "source_url": { "type": "keyword" },
            "connector_type": { "type": "keyword" },
            "owner": { "type": "keyword" },
            "allowed_users": { "type": "keyword" },
            "allowed_groups": { "type": "keyword" },
            "user_permissions": { "type": "object" },
            "group_permissions": { "type": "object" },
            "created_time": { "type": "date" },
            "modified_time": { "type": "date" },
            "indexed_time": { "type": "date" },
            "metadata": { "type": "object" }
        }
    }
}

async def generate_langflow_api_key():
    """Generate Langflow API key using superuser credentials at startup"""
    global LANGFLOW_KEY
    
    # If key already provided via env, do not attempt generation
    if LANGFLOW_KEY:
        print("[INFO] Using LANGFLOW_KEY from environment; skipping generation")
        return LANGFLOW_KEY
    
    if not LANGFLOW_SUPERUSER or not LANGFLOW_SUPERUSER_PASSWORD:
        print("[WARNING] LANGFLOW_SUPERUSER and LANGFLOW_SUPERUSER_PASSWORD not set, skipping API key generation")
        return None
    
    try:
        print("[INFO] Generating Langflow API key using superuser credentials...")
        max_attempts = int(os.getenv("LANGFLOW_KEY_RETRIES", "15"))
        delay_seconds = float(os.getenv("LANGFLOW_KEY_RETRY_DELAY", "2.0"))

        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                # Login to get access token
                login_response = requests.post(
                    f"{LANGFLOW_URL}/api/v1/login",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "username": LANGFLOW_SUPERUSER,
                        "password": LANGFLOW_SUPERUSER_PASSWORD
                    },
                    timeout=10
                )
                login_response.raise_for_status()
                access_token = login_response.json().get("access_token")
                if not access_token:
                    raise KeyError("access_token")

                # Create API key
                api_key_response = requests.post(
                    f"{LANGFLOW_URL}/api/v1/api_key/",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {access_token}"
                    },
                    json={"name": "openrag-auto-generated"},
                    timeout=10
                )
                api_key_response.raise_for_status()
                api_key = api_key_response.json().get("api_key")
                if not api_key:
                    raise KeyError("api_key")

                LANGFLOW_KEY = api_key
                print(f"[INFO] Successfully generated Langflow API key: {api_key[:8]}...")
                return api_key
            except (requests.exceptions.RequestException, KeyError) as e:
                last_error = e
                print(f"[WARN] Attempt {attempt}/{max_attempts} to generate Langflow API key failed: {e}")
                if attempt < max_attempts:
                    time.sleep(delay_seconds)
                else:
                    raise
    
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to generate Langflow API key: {e}")
        return None
    except KeyError as e:
        print(f"[ERROR] Unexpected response format from Langflow: missing {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error generating Langflow API key: {e}")
        return None

class AppClients:
    def __init__(self):
        self.opensearch = None
        self.langflow_client = None
        self.patched_async_client = None
        self.converter = None
        
    async def initialize(self):
        # Generate Langflow API key first
        await generate_langflow_api_key()
        
        # Initialize OpenSearch client
        self.opensearch = AsyncOpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            connection_class=AIOHttpConnection,
            scheme="https",
            use_ssl=True,
            verify_certs=False,
            ssl_assert_fingerprint=None,
            http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
            http_compress=True,
        )
        
        # Initialize Langflow client with generated/provided API key
        if LANGFLOW_KEY and self.langflow_client is None:
            try:
                self.langflow_client = AsyncOpenAI(
                    base_url=f"{LANGFLOW_URL}/api/v1",
                    api_key=LANGFLOW_KEY
                )
            except Exception as e:
                print(f"[WARNING] Failed to initialize Langflow client: {e}")
                self.langflow_client = None
        if self.langflow_client is None:
            print("[WARNING] No Langflow client initialized yet; will attempt later on first use")
        
        # Initialize patched OpenAI client
        self.patched_async_client = patch_openai_with_mcp(AsyncOpenAI())
        
        # Initialize document converter
        self.converter = DocumentConverter()
        
        return self

    async def ensure_langflow_client(self):
        """Ensure Langflow client exists; try to generate key and create client lazily."""
        if self.langflow_client is not None:
            return self.langflow_client
        # Try generating key again (with retries)
        await generate_langflow_api_key()
        if LANGFLOW_KEY and self.langflow_client is None:
            try:
                self.langflow_client = AsyncOpenAI(
                    base_url=f"{LANGFLOW_URL}/api/v1",
                    api_key=LANGFLOW_KEY
                )
                print("[INFO] Langflow client initialized on-demand")
            except Exception as e:
                print(f"[ERROR] Failed to initialize Langflow client on-demand: {e}")
                self.langflow_client = None
        return self.langflow_client
    
    def create_user_opensearch_client(self, jwt_token: str):
        """Create OpenSearch client with user's JWT token for OIDC auth"""
        headers = {'Authorization': f'Bearer {jwt_token}'}
        
        return AsyncOpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            connection_class=AIOHttpConnection,
            scheme="https",
            use_ssl=True,
            verify_certs=False,
            ssl_assert_fingerprint=None,
            headers=headers,
            http_compress=True,
        )

# Global clients instance
clients = AppClients()
