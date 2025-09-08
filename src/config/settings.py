import os
import time

import httpx
import requests
from agentd.patch import patch_openai_with_mcp
from docling.document_converter import DocumentConverter
from dotenv import load_dotenv
from openai import AsyncOpenAI
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection

from utils.logging_config import get_logger

load_dotenv()
load_dotenv("../")

logger = get_logger(__name__)

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
LANGFLOW_INGEST_FLOW_ID = os.getenv("LANGFLOW_INGEST_FLOW_ID")

if _legacy_flow_id and not os.getenv("LANGFLOW_CHAT_FLOW_ID"):
    logger.warning("FLOW_ID is deprecated. Please use LANGFLOW_CHAT_FLOW_ID instead")
    LANGFLOW_CHAT_FLOW_ID = _legacy_flow_id


# Langflow superuser credentials for API key generation
LANGFLOW_SUPERUSER = os.getenv("LANGFLOW_SUPERUSER")
LANGFLOW_SUPERUSER_PASSWORD = os.getenv("LANGFLOW_SUPERUSER_PASSWORD")
# Allow explicit key via environment; generation will be skipped if set
LANGFLOW_KEY = os.getenv("LANGFLOW_KEY")
SESSION_SECRET = os.getenv("SESSION_SECRET", "your-secret-key-change-in-production")
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

# Ingestion configuration
DISABLE_INGEST_WITH_LANGFLOW = os.getenv("DISABLE_INGEST_WITH_LANGFLOW", "false").lower() in ("true", "1", "yes")


def is_no_auth_mode():
    """Check if we're running in no-auth mode (OAuth credentials missing)"""
    result = not (GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)
    logger.debug(
        "Checking auth mode",
        no_auth_mode=result,
        has_client_id=GOOGLE_OAUTH_CLIENT_ID is not None,
        has_client_secret=GOOGLE_OAUTH_CLIENT_SECRET is not None,
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
                    "name": "disk_ann",
                    "engine": "jvector",
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

    logger.debug(
        "generate_langflow_api_key called", current_key_present=bool(LANGFLOW_KEY)
    )

    # If key already provided via env, do not attempt generation
    if LANGFLOW_KEY:
        if os.getenv("LANGFLOW_KEY"):
            logger.info("Using LANGFLOW_KEY from environment; skipping generation")
            return LANGFLOW_KEY
        else:
            # We have a cached key, but let's validate it first
            logger.debug("Validating cached LANGFLOW_KEY", key_prefix=LANGFLOW_KEY[:8])
            try:
                validation_response = requests.get(
                    f"{LANGFLOW_URL}/api/v1/users/whoami",
                    headers={"x-api-key": LANGFLOW_KEY},
                    timeout=5,
                )
                if validation_response.status_code == 200:
                    logger.debug("Cached API key is valid", key_prefix=LANGFLOW_KEY[:8])
                    return LANGFLOW_KEY
                else:
                    logger.warning(
                        "Cached API key is invalid, generating fresh key",
                        status_code=validation_response.status_code,
                    )
                    LANGFLOW_KEY = None  # Clear invalid key
            except Exception as e:
                logger.warning(
                    "Cached API key validation failed, generating fresh key",
                    error=str(e),
                )
                LANGFLOW_KEY = None  # Clear invalid key

    if not LANGFLOW_SUPERUSER or not LANGFLOW_SUPERUSER_PASSWORD:
        logger.warning(
            "LANGFLOW_SUPERUSER and LANGFLOW_SUPERUSER_PASSWORD not set, skipping API key generation"
        )
        return None

    try:
        logger.info("Generating Langflow API key using superuser credentials")
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
                    timeout=10,
                )
                if validation_response.status_code == 200:
                    LANGFLOW_KEY = api_key
                    logger.info(
                        "Successfully generated and validated Langflow API key",
                        key_prefix=api_key[:8],
                    )
                    return api_key
                else:
                    logger.error(
                        "Generated API key validation failed",
                        status_code=validation_response.status_code,
                    )
                    raise ValueError(
                        f"API key validation failed: {validation_response.status_code}"
                    )
            except (requests.exceptions.RequestException, KeyError) as e:
                logger.warning(
                    "Attempt to generate Langflow API key failed",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(e),
                )
                if attempt < max_attempts:
                    time.sleep(delay_seconds)
                else:
                    raise

    except requests.exceptions.RequestException as e:
        logger.error("Failed to generate Langflow API key", error=str(e))
        return None
    except KeyError as e:
        logger.error("Unexpected response format from Langflow", missing_field=str(e))
        return None
    except Exception as e:
        logger.error("Unexpected error generating Langflow API key", error=str(e))
        return None


class AppClients:
    def __init__(self):
        self.opensearch = None
        self.langflow_client = None
        self.langflow_http_client = None
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
                    logger.info(
                        "Langflow client initialized - OPENSEARCH_PASSWORD should be available via environment variables"
                    )
            except Exception as e:
                logger.warning("Failed to initialize Langflow client", error=str(e))
                self.langflow_client = None
        if self.langflow_client is None:
            logger.warning(
                "No Langflow client initialized yet, will attempt later on first use"
            )

        # Initialize patched OpenAI client
        self.patched_async_client = patch_openai_with_mcp(AsyncOpenAI())

        # Initialize document converter
        self.converter = DocumentConverter()

        # Initialize Langflow HTTP client
        self.langflow_http_client = httpx.AsyncClient(
            base_url=LANGFLOW_URL, timeout=60.0
        )

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
                logger.info("Langflow client initialized on-demand")
            except Exception as e:
                logger.error(
                    "Failed to initialize Langflow client on-demand", error=str(e)
                )
                self.langflow_client = None
        return self.langflow_client

    async def langflow_request(self, method: str, endpoint: str, **kwargs):
        """Central method for all Langflow API requests"""
        api_key = await generate_langflow_api_key()
        if not api_key:
            raise ValueError("No Langflow API key available")

        # Merge headers properly - passed headers take precedence over defaults
        default_headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        existing_headers = kwargs.pop("headers", {})
        headers = {**default_headers, **existing_headers}

        # Remove Content-Type if explicitly set to None (for file uploads)
        if headers.get("Content-Type") is None:
            headers.pop("Content-Type", None)

        url = f"{LANGFLOW_URL}{endpoint}"

        return await self.langflow_http_client.request(
            method=method, url=url, headers=headers, **kwargs
        )

    async def _create_langflow_global_variable(self, name: str, value: str):
        """Create a global variable in Langflow via API"""
        api_key = await generate_langflow_api_key()
        if not api_key:
            logger.warning(
                "Cannot create Langflow global variable: No API key", variable_name=name
            )
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
                    logger.info(
                        "Successfully created Langflow global variable",
                        variable_name=name,
                    )
                elif response.status_code == 400 and "already exists" in response.text:
                    logger.info(
                        "Langflow global variable already exists", variable_name=name
                    )
                else:
                    logger.warning(
                        "Failed to create Langflow global variable",
                        variable_name=name,
                        status_code=response.status_code,
                    )
        except Exception as e:
            logger.error(
                "Exception creating Langflow global variable",
                variable_name=name,
                error=str(e),
            )

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
