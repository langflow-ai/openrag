"""OpenSearch index/security initialization at startup.

Pure functions that create or update OpenSearch indices and apply security
configuration. Imported by app startup orchestration and by api/* modules
that need to (re)create the documents index after onboarding completes.
"""

from config.settings import (
    API_KEYS_INDEX_BODY,
    API_KEYS_INDEX_NAME,
    INDEX_BODY,
    clients,
    get_index_name,
    get_openrag_config,
)
from utils.embeddings import create_index_body
from utils.logging_config import get_logger
from utils.telemetry import Category, MessageId, TelemetryClient

logger = get_logger(__name__)


async def wait_for_opensearch(opensearch_client=None):
    """Wait for OpenSearch to be ready, delegating to the shared utility."""
    from utils.opensearch_utils import (
        OpenSearchNotReadyError,
    )
    from utils.opensearch_utils import (
        wait_for_opensearch as _wait_for_opensearch,
    )

    try:
        await _wait_for_opensearch(opensearch_client or clients.opensearch)
        await TelemetryClient.send_event(
            Category.OPENSEARCH_SETUP, MessageId.ORB_OS_CONN_ESTABLISHED
        )
    except OpenSearchNotReadyError:
        await TelemetryClient.send_event(Category.OPENSEARCH_SETUP, MessageId.ORB_OS_TIMEOUT)
        raise


async def configure_alerting_security():
    """Configure OpenSearch alerting plugin security settings"""
    try:
        alerting_settings = {
            "persistent": {
                "plugins.alerting.filter_by_backend_roles": "false",
                "opendistro.alerting.filter_by_backend_roles": "false",
                "opensearch.notifications.general.filter_by_backend_roles": "false",
            }
        }

        response = await clients.opensearch.cluster.put_settings(body=alerting_settings)
        logger.info("Alerting security settings configured successfully", response=response)
    except Exception as e:
        logger.error("Failed to configure alerting security settings", error=str(e))


async def _ensure_opensearch_index():
    """Ensure OpenSearch index exists when using traditional connector service."""
    try:
        index_name = get_index_name()
        if await clients.opensearch.indices.exists(index=index_name):
            logger.info("[OPENSEARCH] Index already exists", index_name=index_name)
            return

        await clients.opensearch.indices.create(index=index_name, body=INDEX_BODY)
        logger.info(
            "Created OpenSearch index for traditional connector service",
            index_name=index_name,
            vector_dimensions=INDEX_BODY["mappings"]["properties"]["chunk_embedding"]["dimension"],
        )
        await TelemetryClient.send_event(Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_CREATED)

    except Exception as e:
        logger.error(
            "Failed to initialize OpenSearch index for traditional connector service",
            error=str(e),
            index_name=get_index_name(),
        )
        await TelemetryClient.send_event(
            Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_CREATE_FAIL
        )


async def init_index(opensearch_client=None, admin_username: str = None):
    """Initialize OpenSearch index and security roles"""
    os_client = opensearch_client or clients.opensearch
    try:
        await wait_for_opensearch(opensearch_client)

        from utils.opensearch_utils import setup_opensearch_security

        await setup_opensearch_security(os_client, admin_username=admin_username)

        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model

        index_body = await create_index_body()

        index_name = get_index_name()
        if not await os_client.indices.exists(index=index_name):
            await os_client.indices.create(index=index_name, body=index_body)
            logger.info(
                "Created OpenSearch index",
                index_name=index_name,
                embedding_model=embedding_model,
            )
            await TelemetryClient.send_event(
                Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_CREATED
            )
        else:
            logger.info(
                "Index already exists, skipping creation and changing number of replicas",
                index_name=index_name,
                embedding_model=embedding_model,
            )
            current = await os_client.indices.get_settings(index=index_name)
            current_replicas = int(
                current[index_name]["settings"]["index"].get("number_of_replicas", 1)
            )
            if current_replicas != 0:
                await os_client.indices.put_settings(
                    index=index_name,
                    body={"index": {"number_of_replicas": 0}},
                )
                logger.info(
                    "Updated documents index settings",
                )
            await TelemetryClient.send_event(
                Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_EXISTS
            )

        knowledge_filter_index_name = "knowledge_filters"
        knowledge_filter_index_body = {
            "settings": {
                "index": {"number_of_replicas": 0, "number_of_shards": 1},
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "standard"},
                    "description": {"type": "text", "analyzer": "standard"},
                    "query_data": {"type": "text"},
                    "owner": {"type": "keyword"},
                    "allowed_users": {"type": "keyword"},
                    "allowed_groups": {"type": "keyword"},
                    "subscriptions": {"type": "object"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            },
        }

        if not await os_client.indices.exists(index=knowledge_filter_index_name):
            await os_client.indices.create(
                index=knowledge_filter_index_name, body=knowledge_filter_index_body
            )
            logger.info(
                "Created knowledge filters index",
                index_name=knowledge_filter_index_name,
            )
            await TelemetryClient.send_event(
                Category.OPENSEARCH_INDEX, MessageId.ORB_OS_KF_INDEX_CREATED
            )
        else:
            logger.info(
                "Knowledge filters index already exists, skipping creation",
                index_name=knowledge_filter_index_name,
            )

            current = await os_client.indices.get_settings(index=knowledge_filter_index_name)
            current_replicas = int(
                current[knowledge_filter_index_name]["settings"]["index"].get(
                    "number_of_replicas", 1
                )
            )
            if current_replicas != 0:
                await os_client.indices.put_settings(
                    index=knowledge_filter_index_name,
                    body={"index": {"number_of_replicas": 0}},
                )
                logger.info(
                    "Updated knowledge filters index settings",
                )

        if not await os_client.indices.exists(index=API_KEYS_INDEX_NAME):
            await os_client.indices.create(index=API_KEYS_INDEX_NAME, body=API_KEYS_INDEX_BODY)
            logger.info("Created API keys index", index_name=API_KEYS_INDEX_NAME)
        else:
            logger.info(
                "API keys index already exists, skipping creation",
                index_name=API_KEYS_INDEX_NAME,
            )

        await configure_alerting_security()

    except Exception as e:
        from utils.opensearch_utils import OpenSearchDiskSpaceError, is_disk_space_error

        if is_disk_space_error(e):
            logger.error(
                "OpenSearch disk space exceeded watermark. Index creation failed."
            )
            raise OpenSearchDiskSpaceError(
                "OpenSearch disk space is full (watermark exceeded). "
                "Please free up disk space on your Docker volume or host machine to continue."
            ) from e
        raise
