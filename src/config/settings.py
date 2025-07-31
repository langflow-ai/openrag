import os
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
FLOW_ID = os.getenv("FLOW_ID")
LANGFLOW_KEY = os.getenv("LANGFLOW_SECRET_KEY")
SESSION_SECRET = os.getenv("SESSION_SECRET", "your-secret-key-change-in-production")
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

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

class AppClients:
    def __init__(self):
        self.opensearch = None
        self.langflow_client = None
        self.patched_async_client = None
        self.converter = None
        
    def initialize(self):
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
        
        # Initialize Langflow client
        self.langflow_client = AsyncOpenAI(
            base_url=f"{LANGFLOW_URL}/api/v1",
            api_key=LANGFLOW_KEY
        )
        
        # Initialize patched OpenAI client
        self.patched_async_client = patch_openai_with_mcp(AsyncOpenAI())
        
        # Initialize document converter
        self.converter = DocumentConverter()
        
        return self

# Global clients instance
clients = AppClients()