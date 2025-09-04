import os
import time

import requests
from agentd.patch import patch_openai_with_mcp
from docling.document_converter import DocumentConverter
from dotenv import load_dotenv
from openai import AsyncOpenAI
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection

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
# Backwards compatible flow ID handling with deprecation warnings
_legacy_flow_id = os.getenv("FLOW_ID")

LANGFLOW_CHAT_FLOW_ID = os.getenv("LANGFLOW_CHAT_FLOW_ID") or _legacy_flow_id
LANGFLOW_INGEST_FLOW_ID = os.getenv("LANGFLOW_INGEST_FLOW_ID") or _legacy_flow_id_ingest

if _legacy_flow_id and not os.getenv("LANGFLOW_CHAT_FLOW_ID"):
    print("[WARNING] FLOW_ID is deprecated. Please use LANGFLOW_CHAT_FLOW_ID instead")
    LANGFLOW_CHAT_FLOW_ID = _legacy_flow_id


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
    print(
        f"[DEBUG] is_no_auth_mode() = {result}, CLIENT_ID={GOOGLE_OAUTH_CLIENT_ID is not None}, CLIENT_SECRET={GOOGLE_OAUTH_CLIENT_SECRET is not None}"
    )
    return result


# Webhook configuration - must be set to enable webhooks
WEBHOOK_BASE_URL = os.getenv(
    "WEBHOOK_BASE_URL"
)  # No default - must be explicitly configured

# OpenSearch configuration
INDEX_NAME = "documents"
VECTOR_DIM = 1536
EMBED_MODEL = "text-embedding-3-small"

INDEX_BODY = {
    "settings": {
        "index": {"knn": True},
        "number_of_shards": 1,
        "number_of_replicas": 1,
    },
    "mappings": {
        "properties": {
            "document_id": {"type": "keyword"},
            "filename": {"type": "keyword"},
            "mimetype": {"type": "keyword"},
            "page": {"type": "integer"},
            "text": {"type": "text"},
            "chunk_embedding": {
                "type": "knn_vector",
                "dimension": VECTOR_DIM,
                "method": {
                    "name": "hnsw",
                    "engine": "nmslib",
                    "space_type": "l2",
                    "parameters": {"ef_construction": 100, "m": 16},
                },
            },
            "source_url": {"type": "keyword"},
            "connector_type": {"type": "keyword"},
            "owner": {"type": "keyword"},
            "allowed_users": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "user_permissions": {"type": "object"},
            "group_permissions": {"type": "object"},
            "created_time": {"type": "date"},
            "modified_time": {"type": "date"},
            "indexed_time": {"type": "date"},
            "metadata": {"type": "object"},
        }
    },
}

# Convenience base URL for Langflow REST API
LANGFLOW_BASE_URL = f"{LANGFLOW_URL}/api/v1"


async def generate_langflow_api_key():
    """Generate Langflow API key using superuser credentials at startup"""
    global LANGFLOW_KEY

    print(f"[DEBUG] generate_langflow_api_key called - current LANGFLOW_KEY: {'present' if LANGFLOW_KEY else 'None'}")

    # If key already provided via env, do not attempt generation
    if LANGFLOW_KEY:
        if os.getenv("LANGFLOW_KEY"):
            print("[INFO] Using LANGFLOW_KEY from environment; skipping generation")
            return LANGFLOW_KEY
        else:
            # We have a cached key, but let's validate it first
            print(f"[DEBUG] Validating cached LANGFLOW_KEY: {LANGFLOW_KEY[:8]}...")
            try:
                validation_response = requests.get(
                    f"{LANGFLOW_URL}/api/v1/users/whoami",
                    headers={"x-api-key": LANGFLOW_KEY},
                    timeout=5
                )
                if validation_response.status_code == 200:
                    print(f"[DEBUG] Cached API key is valid, returning: {LANGFLOW_KEY[:8]}...")
                    return LANGFLOW_KEY
                else:
                    print(f"[WARNING] Cached API key is invalid ({validation_response.status_code}), generating fresh key")
                    LANGFLOW_KEY = None  # Clear invalid key
            except Exception as e:
                print(f"[WARNING] Cached API key validation failed ({e}), generating fresh key")
                LANGFLOW_KEY = None  # Clear invalid key

    if not LANGFLOW_SUPERUSER or not LANGFLOW_SUPERUSER_PASSWORD:
        print(
            "[WARNING] LANGFLOW_SUPERUSER and LANGFLOW_SUPERUSER_PASSWORD not set, skipping API key generation"
        )
        return None

    try:
        print("[INFO] Generating Langflow API key using superuser credentials...")
        max_attempts = int(os.getenv("LANGFLOW_KEY_RETRIES", "15"))
        delay_seconds = float(os.getenv("LANGFLOW_KEY_RETRY_DELAY", "2.0"))

        for attempt in range(1, max_attempts + 1):
            try:
                # Login to get access token
                login_response = requests.post(
                    f"{LANGFLOW_URL}/api/v1/login",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "username": LANGFLOW_SUPERUSER,
                        "password": LANGFLOW_SUPERUSER_PASSWORD,
                    },
                    timeout=10,
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
                        "Authorization": f"Bearer {access_token}",
                    },
                    json={"name": "openrag-auto-generated"},
                    timeout=10,
                )
                api_key_response.raise_for_status()
                api_key = api_key_response.json().get("api_key")
                if not api_key:
                    raise KeyError("api_key")

                # Validate the API key works
                validation_response = requests.get(
                    f"{LANGFLOW_URL}/api/v1/users/whoami",
                    headers={"x-api-key": api_key},
                    timeout=10
                )
                if validation_response.status_code == 200:
                    LANGFLOW_KEY = api_key
                    print(f"[INFO] Successfully generated and validated Langflow API key: {api_key[:8]}...")
                    return api_key
                else:
                    print(f"[ERROR] Generated API key validation failed: {validation_response.status_code}")
                    raise ValueError(f"API key validation failed: {validation_response.status_code}")
            except (requests.exceptions.RequestException, KeyError) as e:
                print(
                    f"[WARN] Attempt {attempt}/{max_attempts} to generate Langflow API key failed: {e}"
                )
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
                if not OPENSEARCH_PASSWORD:
                    raise ValueError("OPENSEARCH_PASSWORD is not set")
                else:
                    await self.ensure_langflow_client()
                    # Note: OPENSEARCH_PASSWORD global variable should be created automatically
                    # via LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT in docker-compose
                    print(
                        "[INFO] Langflow client initialized - OPENSEARCH_PASSWORD should be available via environment variables"
                    )
            except Exception as e:
                print(f"[WARNING] Failed to initialize Langflow client: {e}")
                self.langflow_client = None
        if self.langflow_client is None:
            print(
                "[WARNING] No Langflow client initialized yet; will attempt later on first use"
            )

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
                    base_url=f"{LANGFLOW_URL}/api/v1", api_key=LANGFLOW_KEY
                )
                print("[INFO] Langflow client initialized on-demand")
            except Exception as e:
                print(f"[ERROR] Failed to initialize Langflow client on-demand: {e}")
                self.langflow_client = None
        return self.langflow_client

    async def _create_langflow_global_variable(self, name: str, value: str):
        """Create a global variable in Langflow via API"""
        api_key = await generate_langflow_api_key()
        if not api_key:
            print(f"[WARNING] Cannot create Langflow global variable {name}: No API key")
            return

        url = f"{LANGFLOW_URL}/api/v1/variables/"
        payload = {
            "name": name,
            "value": value,
            "default_fields": [],
            "type": "Credential",
        }
        headers = {"x-api-key": api_key, "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code in [200, 201]:
                    print(f"[INFO] Successfully created Langflow global variable: {name}")
                elif response.status_code == 400 and "already exists" in response.text:
                    print(f"[INFO] Langflow global variable {name} already exists")
                else:
                    print(f"[WARNING] Failed to create Langflow global variable {name}: {response.status_code}")
        except Exception as e:
            print(f"[ERROR] Exception creating Langflow global variable {name}: {e}")

    def create_user_opensearch_client(self, jwt_token: str):
        """Create OpenSearch client with user's JWT token for OIDC auth"""
        headers = {"Authorization": f"Bearer {jwt_token}"}

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
