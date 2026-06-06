"""OpenSearch index/security initialization at startup.

Pure functions that create or update OpenSearch indices and apply security
configuration. Imported by app startup orchestration and by api/* modules
that need to (re)create the documents index after onboarding completes.
"""

from config.settings import (
    ACL_PRINCIPAL_LABELS_MAPPING,
    API_KEYS_INDEX_BODY,
    API_KEYS_INDEX_NAME,
    DLS_PRINCIPAL_INDEX_BODY,
    DLS_PRINCIPAL_INDEX_NAME,
    IBM_AUTH_ENABLED,
    INDEX_BODY,
    OPENRAG_SKIP_OS_SECURITY_SETUP,
    PLATFORM_AUTH_DEV_MODE,
    clients,
    get_index_name,
    get_openrag_config,
)
from utils.embeddings import create_index_body
from utils.logging_config import get_logger
from utils.telemetry import Category, MessageId, TelemetryClient

logger = get_logger(__name__)


async def _ensure_keyword_mappings(os_client, index_name: str, field_names: list[str]) -> None:
    """Add missing keyword mappings to an existing index.

    New ACL fields must be explicit keyword fields before documents are indexed;
    otherwise OpenSearch dynamic mapping can create analyzed text fields that do
    not work for exact-match DLS terms queries.
    """
    try:
        current_mapping = await os_client.indices.get_mapping(index=index_name)
        properties = current_mapping.get(index_name, {}).get("mappings", {}).get("properties", {})
        missing: dict[str, dict[str, str]] = {}
        for field_name in field_names:
            existing = properties.get(field_name)
            if existing is None:
                missing[field_name] = {"type": "keyword"}
            elif existing.get("type") != "keyword":
                logger.warning(
                    "OpenSearch field has incompatible mapping for DLS exact match",
                    index_name=index_name,
                    field_name=field_name,
                    mapping=existing,
                )

        if missing:
            await os_client.indices.put_mapping(
                index=index_name,
                body={"properties": missing},
            )
            logger.info(
                "Updated OpenSearch keyword mappings",
                index_name=index_name,
                fields=list(missing),
            )
    except Exception as e:
        logger.warning(
            "Failed to ensure OpenSearch keyword mappings",
            index_name=index_name,
            fields=field_names,
            error=str(e),
        )


async def _ensure_field_mappings(
    os_client,
    index_name: str,
    field_mappings: dict[str, dict],
) -> None:
    """Add missing explicit mappings to an existing index."""
    try:
        current_mapping = await os_client.indices.get_mapping(index=index_name)
        properties = current_mapping.get(index_name, {}).get("mappings", {}).get("properties", {})
        missing = {
            field_name: mapping
            for field_name, mapping in field_mappings.items()
            if properties.get(field_name) is None
        }

        if missing:
            await os_client.indices.put_mapping(
                index=index_name,
                body={"properties": missing},
            )
            logger.info(
                "Updated OpenSearch field mappings",
                index_name=index_name,
                fields=list(missing),
            )
    except Exception as e:
        logger.warning(
            "Failed to ensure OpenSearch field mappings",
            index_name=index_name,
            fields=list(field_mappings),
            error=str(e),
        )


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
    if IBM_AUTH_ENABLED and PLATFORM_AUTH_DEV_MODE:
        logger.info("Skipping alerting security configuration in IBM dev mode.")
        return

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
    if IBM_AUTH_ENABLED and PLATFORM_AUTH_DEV_MODE:
        logger.info("Skipping OpenSearch index creation in IBM dev mode.")
        return

    try:
        index_name = get_index_name()
        if await clients.opensearch.indices.exists(index=index_name):
            logger.info("[OPENSEARCH] Index already exists", index_name=index_name)
            await _ensure_keyword_mappings(
                clients.opensearch,
                index_name,
                ["allowed_users", "allowed_groups", "allowed_principals", "ingest_run_id"],
            )
            await _ensure_field_mappings(
                clients.opensearch,
                index_name,
                {"allowed_principal_labels": ACL_PRINCIPAL_LABELS_MAPPING},
            )
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
    # Tracks the most recent OpenSearch operation so the except block can name
    # the failing step (TransportError stringifies to just "TransportError(500, '')").
    step = "wait_for_opensearch"
    try:
        await wait_for_opensearch(opensearch_client)

        # Skip security setup when the platform manages it externally
        # (SaaS / CPD). Index creation below still runs — SaaS / CPD
        # deployments still need indices, they just don't want OpenRAG
        # touching roles or role mappings.
        if OPENRAG_SKIP_OS_SECURITY_SETUP:
            logger.info(
                "Skipping OpenSearch security setup during init_index "
                "(OPENRAG_SKIP_OS_SECURITY_SETUP=true)",
                admin_username=admin_username,
            )
        else:
            from utils.opensearch_utils import setup_opensearch_security

            step = "setup_opensearch_security"
            await setup_opensearch_security(os_client, admin_username=admin_username)

        step = "build_index_body"
        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model

        index_body = await create_index_body()

        index_name = get_index_name()
        step = f"documents_index:{index_name}"
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
                "Index already exists, skipping creation",
                index_name=index_name,
                embedding_model=embedding_model,
            )
            await _ensure_keyword_mappings(
                os_client,
                index_name,
                ["allowed_users", "allowed_groups", "allowed_principals", "ingest_run_id"],
            )
            await _ensure_field_mappings(
                os_client,
                index_name,
                {"allowed_principal_labels": ACL_PRINCIPAL_LABELS_MAPPING},
            )
            if not (IBM_AUTH_ENABLED and PLATFORM_AUTH_DEV_MODE):
                # Set number of replicas to 0 to not create unused nodes in OpenSearch, in case it was created with more replicas
                try:
                    current = await os_client.indices.get_settings(index=index_name)
                    current_replicas = int(
                        current[index_name]["settings"]["index"].get("number_of_replicas", 1)
                    )
                    if current_replicas != 0:
                        await os_client.indices.put_settings(
                            index=index_name,
                            body={"index": {"number_of_replicas": 0}},
                        )
                        logger.info("Updated documents index settings")
                except Exception as e:
                    logger.warning(
                        "Failed to check or update index replicas",
                        index_name=index_name,
                        error=str(e),
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
                    "allowed_principals": {"type": "keyword"},
                    "subscriptions": {"type": "object"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            },
        }

        step = f"knowledge_filters_index:{knowledge_filter_index_name}"
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
            await _ensure_keyword_mappings(
                os_client,
                knowledge_filter_index_name,
                ["allowed_users", "allowed_groups", "allowed_principals"],
            )

            if not (IBM_AUTH_ENABLED and PLATFORM_AUTH_DEV_MODE):
                try:
                    current = await os_client.indices.get_settings(
                        index=knowledge_filter_index_name
                    )
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
                        logger.info("Updated knowledge filters index settings")
                except Exception as e:
                    logger.warning(
                        "Failed to check or update knowledge filter index replicas",
                        index_name=knowledge_filter_index_name,
                        error=str(e),
                    )

        step = f"api_keys_index:{API_KEYS_INDEX_NAME}"
        if not await os_client.indices.exists(index=API_KEYS_INDEX_NAME):
            await os_client.indices.create(index=API_KEYS_INDEX_NAME, body=API_KEYS_INDEX_BODY)
            logger.info("Created API keys index", index_name=API_KEYS_INDEX_NAME)
        else:
            logger.info(
                "API keys index already exists, skipping creation",
                index_name=API_KEYS_INDEX_NAME,
            )

        step = f"dls_principal_index:{DLS_PRINCIPAL_INDEX_NAME}"
        if not await os_client.indices.exists(index=DLS_PRINCIPAL_INDEX_NAME):
            await os_client.indices.create(
                index=DLS_PRINCIPAL_INDEX_NAME,
                body=DLS_PRINCIPAL_INDEX_BODY,
            )
            logger.info("Created DLS principal index", index_name=DLS_PRINCIPAL_INDEX_NAME)
        else:
            logger.info(
                "DLS principal index already exists, skipping creation",
                index_name=DLS_PRINCIPAL_INDEX_NAME,
            )
            await _ensure_keyword_mappings(
                os_client,
                DLS_PRINCIPAL_INDEX_NAME,
                ["user_name", "auth_user_id", "auth_email", "provider", "principals"],
            )
            await _ensure_field_mappings(
                os_client,
                DLS_PRINCIPAL_INDEX_NAME,
                {"principal_labels": ACL_PRINCIPAL_LABELS_MAPPING},
            )

        step = "configure_alerting_security"
        await configure_alerting_security()

    except Exception as e:
        from utils.opensearch_utils import (
            OpenSearchDiskSpaceError,
            is_disk_space_error,
            opensearch_error_fields,
        )

        # TransportError stringifies to just "TransportError(500, '')" — surface
        # the failing step plus the OpenSearch status/error/body it carries.
        err_fields = {
            "failed_step": step,
            "error": str(e),
            "error_repr": repr(e),
            **opensearch_error_fields(e),
        }
        logger.error("init_index failed", **err_fields)

        if is_disk_space_error(e):
            logger.error("OpenSearch disk space exceeded watermark. Index creation failed.")
            raise OpenSearchDiskSpaceError(
                "OpenSearch disk space is full (watermark exceeded). "
                "Please free up disk space on your Docker volume or host machine to continue."
            ) from e
        raise
