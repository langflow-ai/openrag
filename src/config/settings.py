import asyncio
import os
import time

import httpx
import requests
from agentd.patch import patch_openai_with_mcp
from dotenv import load_dotenv
from openai import AsyncOpenAI
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection

from utils.container_utils import get_container_host
from utils.document_processing import create_document_converter
from utils.logging_config import get_logger

load_dotenv(override=False)
load_dotenv("../", override=False)

logger = get_logger(__name__)

# Import configuration manager
from .config_manager import config_manager

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
LANGFLOW_URL_INGEST_FLOW_ID = os.getenv("LANGFLOW_URL_INGEST_FLOW_ID")
NUDGES_FLOW_ID = os.getenv("NUDGES_FLOW_ID")

if _legacy_flow_id and not os.getenv("LANGFLOW_CHAT_FLOW_ID"):
    logger.warning("FLOW_ID is deprecated. Please use LANGFLOW_CHAT_FLOW_ID instead")
    LANGFLOW_CHAT_FLOW_ID = _legacy_flow_id


# Langflow superuser credentials for API key generation
LANGFLOW_AUTO_LOGIN = os.getenv("LANGFLOW_AUTO_LOGIN", "False").lower() in ("true", "1", "yes")
LANGFLOW_SUPERUSER = os.getenv("LANGFLOW_SUPERUSER")
LANGFLOW_SUPERUSER_PASSWORD = os.getenv("LANGFLOW_SUPERUSER_PASSWORD")
# Allow explicit key via environment; generation will be skipped if set
LANGFLOW_KEY = os.getenv("LANGFLOW_KEY")
SESSION_SECRET = os.getenv("SESSION_SECRET", "your-secret-key-change-in-production")
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
DOCLING_OCR_ENGINE = os.getenv("DOCLING_OCR_ENGINE")

# Ingestion configuration
DISABLE_INGEST_WITH_LANGFLOW = os.getenv(
    "DISABLE_INGEST_WITH_LANGFLOW", "false"
).lower() in ("true", "1", "yes")

# Langflow HTTP timeout configuration (in seconds)
# For large documents (300+ pages), ingestion can take 30+ minutes
# Default: 40 minutes total, 40 minutes read timeout
LANGFLOW_TIMEOUT = float(os.getenv("LANGFLOW_TIMEOUT", "2400"))  # 40 minutes
LANGFLOW_CONNECT_TIMEOUT = float(os.getenv("LANGFLOW_CONNECT_TIMEOUT", "30"))  # 30 seconds


def is_no_auth_mode():
    """Check if we're running in no-auth mode (OAuth credentials missing)"""
    result = not (GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)
    return result


# Webhook configuration - must be set to enable webhooks
WEBHOOK_BASE_URL = os.getenv(
    "WEBHOOK_BASE_URL"
)  # No default - must be explicitly configured

# OpenSearch configuration
INDEX_NAME = "documents"
VECTOR_DIM = 1536
EMBED_MODEL = "text-embedding-3-small"

OPENAI_EMBEDDING_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

WATSONX_EMBEDDING_DIMENSIONS = {
# IBM Models
"ibm/granite-embedding-107m-multilingual": 384,  
"ibm/granite-embedding-278m-multilingual": 1024,
"ibm/slate-125m-english-rtrvr": 768,
"ibm/slate-125m-english-rtrvr-v2": 768,
"ibm/slate-30m-english-rtrvr": 384,
"ibm/slate-30m-english-rtrvr-v2": 384,
# Third Party Models
"intfloat/multilingual-e5-large": 1024,
"sentence-transformers/all-minilm-l6-v2": 384,
}

INDEX_BODY = {
    "settings": {
        "index": {"knn": True},
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "document_id": {"type": "keyword"},
            "filename": {"type": "keyword"},
            "mimetype": {"type": "keyword"},
            "page": {"type": "integer"},
            "text": {"type": "text"},
            # Legacy field - kept for backward compatibility
            # New documents will use chunk_embedding_{model_name} fields
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
            # Track which embedding model was used for this chunk
            "embedding_model": {"type": "keyword"},
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

# API Keys index for public API authentication
API_KEYS_INDEX_NAME = "api_keys"
API_KEYS_INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "key_id": {"type": "keyword"},
            "key_hash": {"type": "keyword"},  # SHA-256 hash, never store plaintext
            "key_prefix": {"type": "keyword"},  # First 8 chars for display (e.g., "orag_abc1")
            "user_id": {"type": "keyword"},
            "user_email": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "created_at": {"type": "date"},
            "last_used_at": {"type": "date"},
            "revoked": {"type": "boolean"},
        }
    },
}

# Convenience base URL for Langflow REST API
LANGFLOW_BASE_URL = f"{LANGFLOW_URL}/api/v1"


async def get_langflow_api_key(force_regenerate: bool = False):
    """Get the Langflow API key, generating one if needed.

    Args:
        force_regenerate: If True, generates a new key even if one is cached.
                          Used when a request fails with 401/403 to get a fresh key.
    """
    global LANGFLOW_KEY

    logger.debug(
        "get_langflow_api_key called",
        current_key_present=bool(LANGFLOW_KEY),
        force_regenerate=force_regenerate,
    )

    # If we have a cached key and not forcing regeneration, return it
    if LANGFLOW_KEY and not force_regenerate:
        return LANGFLOW_KEY

    # If forcing regeneration, clear the cached key
    if force_regenerate and LANGFLOW_KEY:
        logger.info("Forcing Langflow API key regeneration due to auth failure")
        LANGFLOW_KEY = None

    # Use default langflow/langflow credentials if auto-login is enabled and credentials not set
    username = LANGFLOW_SUPERUSER
    password = LANGFLOW_SUPERUSER_PASSWORD

    if LANGFLOW_AUTO_LOGIN and (not username or not password):
        logger.info("LANGFLOW_AUTO_LOGIN is enabled, using default langflow/langflow credentials")
        username = username or "langflow"
        password = password or "langflow"

    if not username or not password:
        logger.warning(
            "LANGFLOW_SUPERUSER and LANGFLOW_SUPERUSER_PASSWORD not set, skipping API key generation"
        )
        return None

    try:
        logger.info("Generating Langflow API key using superuser credentials")
        max_attempts = int(os.getenv("LANGFLOW_KEY_RETRIES", "15"))
        delay_seconds = float(os.getenv("LANGFLOW_KEY_RETRY_DELAY", "2.0"))

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    # Login to get access token
                    login_response = await client.post(
                        f"{LANGFLOW_URL}/api/v1/login",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data={
                            "username": username,
                            "password": password,
                        },
                    )
                    login_response.raise_for_status()
                    access_token = login_response.json().get("access_token")
                    if not access_token:
                        raise KeyError("access_token")

                    # Create API key
                    api_key_response = await client.post(
                        f"{LANGFLOW_URL}/api/v1/api_key/",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {access_token}",
                        },
                        json={"name": "openrag-auto-generated"},
                    )
                    api_key_response.raise_for_status()
                    api_key = api_key_response.json().get("api_key")
                    if not api_key:
                        raise KeyError("api_key")

                    # Validate the API key works
                    validation_response = await client.get(
                        f"{LANGFLOW_URL}/api/v1/users/whoami",
                        headers={"x-api-key": api_key},
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
                except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as e:
                    logger.warning(
                        "Attempt to generate Langflow API key failed",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error=str(e),
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(delay_seconds)
                    else:
                        raise

    except (httpx.HTTPStatusError, httpx.RequestError) as e:
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
        self._patched_async_client = None  # Private attribute - single client for all providers
        self._client_init_lock = __import__('threading').Lock()  # Lock for thread-safe initialization
        self.converter = None

    async def initialize(self):
        # Generate Langflow API key first
        await get_langflow_api_key()

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

        # Initialize patched OpenAI client if API key is available
        # This allows the app to start even if OPENAI_API_KEY is not set yet
        # (e.g., when it will be provided during onboarding)
        # The property will handle lazy initialization with probe when first accessed
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            logger.info("OpenAI API key found in environment - will be initialized lazily on first use with HTTP/2 probe")
        else:
            logger.info("OpenAI API key not found in environment - will be initialized on first use if needed")

        # Initialize document converter
        self.converter = create_document_converter(ocr_engine=DOCLING_OCR_ENGINE)

        # Initialize Langflow HTTP client with extended timeouts for large documents
        # Use explicit timeout configuration to handle large PDF ingestion (300+ pages)
        self.langflow_http_client = httpx.AsyncClient(
            base_url=LANGFLOW_URL,
            timeout=httpx.Timeout(
                timeout=LANGFLOW_TIMEOUT,  # Total timeout
                connect=LANGFLOW_CONNECT_TIMEOUT,  # Connection timeout
                read=LANGFLOW_TIMEOUT,  # Read timeout (most important for large PDFs)
                write=LANGFLOW_CONNECT_TIMEOUT,  # Write timeout
                pool=LANGFLOW_CONNECT_TIMEOUT,  # Pool timeout
            )
        )
        logger.info(
            "Initialized Langflow HTTP client with extended timeouts",
            timeout_seconds=LANGFLOW_TIMEOUT,
            connect_timeout_seconds=LANGFLOW_CONNECT_TIMEOUT,
        )

        return self

    async def ensure_langflow_client(self):
        """Ensure Langflow client exists; try to generate key and create client lazily."""
        if self.langflow_client is not None:
            return self.langflow_client
        # Try generating key again (with retries)
        await get_langflow_api_key()
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

    @property
    def patched_async_client(self):
        """
        Property that ensures OpenAI client is initialized on first access.
        This allows lazy initialization so the app can start without an API key.

        The client is patched with LiteLLM support to handle multiple providers.
        All provider credentials are loaded into environment for LiteLLM routing.

        Note: The client is a long-lived singleton that should be closed via cleanup().
        Thread-safe via lock to prevent concurrent initialization attempts.
        """
        # Quick check without lock
        if self._patched_async_client is not None:
            return self._patched_async_client

        # Use lock to ensure only one thread initializes
        with self._client_init_lock:
            # Double-check after acquiring lock
            if self._patched_async_client is not None:
                return self._patched_async_client

            # Load all provider credentials into environment for LiteLLM
            # LiteLLM routes based on model name prefixes (openai/, ollama/, watsonx/, etc.)
            try:
                config = get_openrag_config()
                
                # Set OpenAI credentials
                if config.providers.openai.api_key:
                    os.environ["OPENAI_API_KEY"] = config.providers.openai.api_key
                    logger.debug("Loaded OpenAI API key from config")
                
                # Set Anthropic credentials
                if config.providers.anthropic.api_key:
                    os.environ["ANTHROPIC_API_KEY"] = config.providers.anthropic.api_key
                    logger.debug("Loaded Anthropic API key from config")
                
                # Set WatsonX credentials
                if config.providers.watsonx.api_key:
                    os.environ["WATSONX_API_KEY"] = config.providers.watsonx.api_key
                if config.providers.watsonx.endpoint:
                    os.environ["WATSONX_ENDPOINT"] = config.providers.watsonx.endpoint
                    os.environ["WATSONX_API_BASE"] = config.providers.watsonx.endpoint  # LiteLLM expects this name
                if config.providers.watsonx.project_id:
                    os.environ["WATSONX_PROJECT_ID"] = config.providers.watsonx.project_id
                if config.providers.watsonx.api_key:
                    logger.debug("Loaded WatsonX credentials from config")
                
                # Set Ollama endpoint
                if config.providers.ollama.endpoint:
                    os.environ["OLLAMA_BASE_URL"] = config.providers.ollama.endpoint
                    os.environ["OLLAMA_ENDPOINT"] = config.providers.ollama.endpoint
                    logger.debug("Loaded Ollama endpoint from config")
                    
            except Exception as e:
                logger.debug("Could not load provider credentials from config", error=str(e))

            # Try to initialize the client - AsyncOpenAI() will read from environment
            # We'll try HTTP/2 first with a probe, then fall back to HTTP/1.1 if it times out
            import asyncio
            import concurrent.futures
            import threading

            async def probe_and_initialize():
                # Try HTTP/2 first (default)
                client_http2 = patch_openai_with_mcp(AsyncOpenAI())
                logger.info("Probing OpenAI client with HTTP/2...")

                try:
                    # Probe with a small embedding and short timeout
                    await asyncio.wait_for(
                        client_http2.embeddings.create(
                            model='text-embedding-3-small',
                            input=['test']
                        ),
                        timeout=5.0
                    )
                    logger.info("OpenAI client initialized with HTTP/2 (probe successful)")
                    return client_http2
                except (asyncio.TimeoutError, Exception) as probe_error:
                    logger.warning("HTTP/2 probe failed, falling back to HTTP/1.1", error=str(probe_error))
                    # Close the HTTP/2 client
                    try:
                        await client_http2.close()
                    except Exception:
                        pass

                    # Fall back to HTTP/1.1 with explicit timeout settings
                    http_client = httpx.AsyncClient(
                        http2=False,
                        timeout=httpx.Timeout(60.0, connect=10.0)
                    )
                    client_http1 = patch_openai_with_mcp(
                        AsyncOpenAI(http_client=http_client)
                    )
                    logger.info("OpenAI client initialized with HTTP/1.1 (fallback)")
                    return client_http1

            def run_probe_in_thread():
                """Run the async probe in a new thread with its own event loop"""
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(probe_and_initialize())
                finally:
                    loop.close()

            try:
                # Run the probe in a separate thread with its own event loop
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_probe_in_thread)
                    self._patched_async_client = future.result(timeout=15)
                logger.info("Successfully initialized OpenAI client")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e.__class__.__name__}: {str(e)}")
                raise ValueError(f"Failed to initialize OpenAI client: {str(e)}. Please complete onboarding or set OPENAI_API_KEY environment variable.")

            return self._patched_async_client

    @property
    def patched_llm_client(self):
        """Alias for patched_async_client - for backward compatibility with code expecting separate clients."""
        return self.patched_async_client

    @property
    def patched_embedding_client(self):
        """Alias for patched_async_client - for backward compatibility with code expecting separate clients."""
        return self.patched_async_client

    async def refresh_patched_client(self):
        """Reset patched client so next use picks up updated provider credentials."""
        if self._patched_async_client is not None:
            try:
                await self._patched_async_client.close()
                logger.info("Closed patched client for refresh")
            except Exception as e:
                logger.warning("Failed to close patched client during refresh", error=str(e))
            finally:
                self._patched_async_client = None

    async def cleanup(self):
        """Cleanup resources - should be called on application shutdown"""
        # Close AsyncOpenAI client if it was created
        if self._patched_async_client is not None:
            try:
                await self._patched_async_client.close()
                logger.info("Closed AsyncOpenAI client")
            except Exception as e:
                logger.error("Failed to close AsyncOpenAI client", error=str(e))
            finally:
                self._patched_async_client = None

        # Close Langflow HTTP client if it exists
        if self.langflow_http_client is not None:
            try:
                await self.langflow_http_client.aclose()
                logger.info("Closed Langflow HTTP client")
            except Exception as e:
                logger.error("Failed to close Langflow HTTP client", error=str(e))
            finally:
                self.langflow_http_client = None

        # Close OpenSearch client if it exists
        if self.opensearch is not None:
            try:
                await self.opensearch.close()
                logger.info("Closed OpenSearch client")
            except Exception as e:
                logger.error("Failed to close OpenSearch client", error=str(e))
            finally:
                self.opensearch = None

        # Close Langflow client if it exists (also an AsyncOpenAI client)
        if self.langflow_client is not None:
            try:
                await self.langflow_client.close()
                logger.info("Closed Langflow client")
            except Exception as e:
                logger.error("Failed to close Langflow client", error=str(e))
            finally:
                self.langflow_client = None

    async def langflow_request(self, method: str, endpoint: str, **kwargs):
        """Central method for all Langflow API requests.

        Retries once with a fresh API key on auth failures (401/403).
        """
        api_key = await get_langflow_api_key()
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

        response = await self.langflow_http_client.request(
            method=method, url=url, headers=headers, **kwargs
        )

        # Retry once with a fresh API key on auth failure
        if response.status_code in (401, 403):
            logger.warning(
                "Langflow request auth failed, regenerating API key and retrying",
                status_code=response.status_code,
                endpoint=endpoint,
            )
            api_key = await get_langflow_api_key(force_regenerate=True)
            if api_key:
                headers["x-api-key"] = api_key
                response = await self.langflow_http_client.request(
                    method=method, url=url, headers=headers, **kwargs
                )

        return response

    async def _create_langflow_global_variable(
        self, name: str, value: str, modify: bool = False
    ):
        """Create a global variable in Langflow via API"""
        payload = {
            "name": name,
            "value": value,
            "default_fields": [],
            "type": "Credential",
        }

        try:
            response = await self.langflow_request(
                "POST", "/api/v1/variables/", json=payload
            )

            if response.status_code in [200, 201]:
                logger.info(
                    "Successfully created Langflow global variable",
                    variable_name=name,
                )
            elif response.status_code == 400 and "already exists" in response.text:
                if modify:
                    logger.info(
                        "Langflow global variable already exists, attempting to update",
                        variable_name=name,
                    )
                    await self._update_langflow_global_variable(name, value)
                else:
                    logger.info(
                        "Langflow global variable already exists",
                        variable_name=name,
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

    async def _update_langflow_global_variable(self, name: str, value: str):
        """Update an existing global variable in Langflow via API"""
        try:
            # First, get all variables to find the one with the matching name
            get_response = await self.langflow_request("GET", "/api/v1/variables/")

            if get_response.status_code != 200:
                logger.error(
                    "Failed to retrieve variables for update",
                    variable_name=name,
                    status_code=get_response.status_code,
                )
                return

            variables = get_response.json()
            target_variable = None

            # Find the variable with matching name
            for variable in variables:
                if variable.get("name") == name:
                    target_variable = variable
                    break

            if not target_variable:
                logger.error("Variable not found for update", variable_name=name)
                return

            variable_id = target_variable.get("id")
            if not variable_id:
                logger.error("Variable ID not found for update", variable_name=name)
                return

            # Update the variable using PATCH
            update_payload = {
                "id": variable_id,
                "name": name,
                "value": value,
                "default_fields": target_variable.get("default_fields", []),
            }

            patch_response = await self.langflow_request(
                "PATCH", f"/api/v1/variables/{variable_id}", json=update_payload
            )

            if patch_response.status_code == 200:
                logger.info(
                    "Successfully updated Langflow global variable",
                    variable_name=name,
                    variable_id=variable_id,
                )
            else:
                logger.warning(
                    "Failed to update Langflow global variable",
                    variable_name=name,
                    variable_id=variable_id,
                    status_code=patch_response.status_code,
                    response_text=patch_response.text,
                )

        except Exception as e:
            logger.error(
                "Exception updating Langflow global variable",
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
            timeout=30,  # 30 second timeout
            max_retries=3,
            retry_on_timeout=True,
        )


# Component template paths
WATSONX_LLM_COMPONENT_PATH = os.getenv(
    "WATSONX_LLM_COMPONENT_PATH", "flows/components/watsonx_llm.json"
)
WATSONX_LLM_TEXT_COMPONENT_PATH = os.getenv(
    "WATSONX_LLM_TEXT_COMPONENT_PATH", "flows/components/watsonx_llm_text.json"
)
WATSONX_EMBEDDING_COMPONENT_PATH = os.getenv(
    "WATSONX_EMBEDDING_COMPONENT_PATH", "flows/components/watsonx_embedding.json"
)
OLLAMA_LLM_COMPONENT_PATH = os.getenv(
    "OLLAMA_LLM_COMPONENT_PATH", "flows/components/ollama_llm.json"
)
OLLAMA_LLM_TEXT_COMPONENT_PATH = os.getenv(
    "OLLAMA_LLM_TEXT_COMPONENT_PATH", "flows/components/ollama_llm_text.json"
)
OLLAMA_EMBEDDING_COMPONENT_PATH = os.getenv(
    "OLLAMA_EMBEDDING_COMPONENT_PATH", "flows/components/ollama_embedding.json"
)

# Component IDs in flows

OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME = os.getenv(
    "OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME", "Embedding Model"
)
OPENAI_LLM_COMPONENT_DISPLAY_NAME = os.getenv(
    "OPENAI_LLM_COMPONENT_DISPLAY_NAME", "Language Model"
)

AGENT_COMPONENT_DISPLAY_NAME = os.getenv(
    "AGENT_COMPONENT_DISPLAY_NAME", "Agent"
)

# Provider-specific component IDs
WATSONX_EMBEDDING_COMPONENT_DISPLAY_NAME = os.getenv(
    "WATSONX_EMBEDDING_COMPONENT_DISPLAY_NAME", "IBM watsonx.ai Embeddings"
)
WATSONX_LLM_COMPONENT_DISPLAY_NAME = os.getenv(
    "WATSONX_LLM_COMPONENT_DISPLAY_NAME", "IBM watsonx.ai"
)

OLLAMA_EMBEDDING_COMPONENT_DISPLAY_NAME = os.getenv(
    "OLLAMA_EMBEDDING_COMPONENT_DISPLAY_NAME", "Ollama Embeddings"
)
OLLAMA_LLM_COMPONENT_DISPLAY_NAME = os.getenv("OLLAMA_LLM_COMPONENT_DISPLAY_NAME", "Ollama")

# Docling component ID for ingest flow
DOCLING_COMPONENT_DISPLAY_NAME = os.getenv("DOCLING_COMPONENT_DISPLAY_NAME", "Docling Serve")

LOCALHOST_URL = get_container_host() or "localhost"

# Global clients instance
clients = AppClients()


# Configuration access
def get_openrag_config():
    """Get current OpenRAG configuration."""
    return config_manager.get_config()


# Expose configuration settings for backward compatibility and easy access
def get_provider_config():
    """Get provider configuration."""
    return get_openrag_config().provider


def get_knowledge_config():
    """Get knowledge configuration."""
    return get_openrag_config().knowledge


def get_agent_config():
    """Get agent configuration."""
    return get_openrag_config().agent


def get_embedding_model() -> str:
    """Return the currently configured embedding model."""
    return get_openrag_config().knowledge.embedding_model or EMBED_MODEL if DISABLE_INGEST_WITH_LANGFLOW else ""
