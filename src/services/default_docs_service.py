"""Default OpenRAG docs ingestion / refresh / upgrade-reingest.

This module owns the bundled-docs onboarding flow: deciding whether to
ingest from a URL or from local files, choosing the Langflow or
direct-OpenRAG pipeline, detecting upstream content changes via HTTP
ETag/Last-Modified, and deleting stale chunks before reingestion.

Public entry points used outside this module:
- ingest_default_documents_when_ready  (api/settings.py)
- refresh_default_openrag_docs         (api/settings.py)
- _get_remote_docs_signature           (test_main_docs_signature.py)
"""

import hashlib
import os

import httpx

from config.paths import get_documents_path
from config.settings import (
    DEFAULT_DOCS_CRAWL_DEPTH,
    DEFAULT_DOCS_INGEST_SOURCE,
    DEFAULT_DOCS_URL,
    DISABLE_INGEST_WITH_LANGFLOW,
    LANGFLOW_URL_INGEST_FLOW_ID,
    config_manager,
    get_index_name,
    get_openrag_config,
)
from utils.logging_config import get_logger
from utils.telemetry import Category, MessageId, TelemetryClient
from utils.url_content_fetcher import materialize_url_as_text_file
from utils.version_utils import OPENRAG_VERSION

logger = get_logger(__name__)

# Files to exclude from startup ingestion
EXCLUDED_INGESTION_FILES = {"warmup_ocr.pdf"}
URL_INGEST_EXCLUDED_INGESTION_FILES = {"openrag-documentation.pdf"}


def _get_documents_dir():
    """Get the documents directory path, handling both Docker and local environments."""
    path = get_documents_path()
    logger.debug(f"Using documents path: {path}")
    return path


def _should_use_url_default_docs_ingest() -> bool:
    """Return whether default docs ingestion should use URL crawling."""
    return DEFAULT_DOCS_INGEST_SOURCE == "url" and bool(DEFAULT_DOCS_URL)


async def ingest_openrag_docs_when_ready(
    document_service,
    models_service,
    task_service,
    langflow_file_service,
    session_manager,
    jwt_token=None,
):
    """Ingest OpenRAG docs during onboarding."""
    use_url_ingest = _should_use_url_default_docs_ingest()
    task_id = None
    if use_url_ingest:
        try:
            await TelemetryClient.send_event(
                Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_URL_START
            )
            if DISABLE_INGEST_WITH_LANGFLOW:
                task_id = await _ingest_default_documents_url(
                    document_service=document_service,
                    models_service=models_service,
                    docs_url=DEFAULT_DOCS_URL,
                    crawl_depth=DEFAULT_DOCS_CRAWL_DEPTH,
                    jwt_token=jwt_token,
                )
            else:
                logger.info(
                    "Ingesting default documents using Langflow",
                    docs_url=DEFAULT_DOCS_URL,
                )
                task_id = await _ingest_default_documents_url_langflow(
                    langflow_file_service=langflow_file_service,
                    session_manager=session_manager,
                    task_service=task_service,
                    docs_url=DEFAULT_DOCS_URL,
                    crawl_depth=DEFAULT_DOCS_CRAWL_DEPTH,
                    jwt_token=jwt_token,
                )
            await TelemetryClient.send_event(
                Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_URL_COMPLETE
            )
        except Exception as e:
            logger.error("Default URL documents ingestion failed", error=str(e))
            await TelemetryClient.send_event(
                Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_URL_FAILED
            )
    return task_id


async def ingest_default_documents_when_ready(
    document_service,
    models_service,
    task_service,
    langflow_file_service,
    session_manager,
    jwt_token=None,
):
    """Ingest default OpenRAG docs during onboarding."""
    try:
        logger.info(
            "Ingesting default documents when ready",
            disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW,
            ingest_source=DEFAULT_DOCS_INGEST_SOURCE,
        )
        await TelemetryClient.send_event(
            Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_START
        )
        task_id = await ingest_openrag_docs_when_ready(
            document_service,
            models_service,
            task_service,
            langflow_file_service,
            session_manager,
            jwt_token=jwt_token,
        )

        base_dir = _get_documents_dir()
        if not os.path.isdir(base_dir):
            raise FileNotFoundError(f"Default documents directory not found: {base_dir}")

        excluded_files = set(EXCLUDED_INGESTION_FILES)
        if _should_use_url_default_docs_ingest():
            excluded_files.update(URL_INGEST_EXCLUDED_INGESTION_FILES)

        file_paths = [
            os.path.join(root, fn)
            for root, _, files in os.walk(base_dir)
            for fn in files
            if fn not in excluded_files
        ]

        if not file_paths:
            raise FileNotFoundError(f"No default documents found in {base_dir}")

        if DISABLE_INGEST_WITH_LANGFLOW:
            new_task_id = await _ingest_default_documents_openrag(
                document_service,
                models_service,
                task_service,
                file_paths,
                existing_task_id=task_id,
                connector_type="local",
                jwt_token=jwt_token,
            )
            task_id = new_task_id or task_id
        else:
            new_task_id = await _ingest_default_documents_langflow(
                langflow_file_service,
                session_manager,
                task_service,
                file_paths,
                existing_task_id=task_id,
                connector_type="local",
                jwt_token=jwt_token,
            )
            task_id = new_task_id or task_id

        await TelemetryClient.send_event(
            Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_COMPLETE
        )

        return task_id

    except Exception as e:
        logger.error("Default documents ingestion failed", error=str(e))
        await TelemetryClient.send_event(
            Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_FAILED
        )
        raise


async def _ingest_default_documents_langflow(
    langflow_file_service,
    session_manager,
    task_service,
    file_paths,
    existing_task_id: str = None,
    connector_type: str = "openrag_docs",
    jwt_token=None,
):
    """Ingest default documents using Langflow upload-ingest-delete pipeline."""

    logger.info(
        "Using Langflow ingestion pipeline for default documents",
        file_count=len(file_paths),
    )

    from session_manager import AnonymousUser

    anonymous_user = AnonymousUser()
    effective_jwt = jwt_token

    if not effective_jwt and session_manager:
        session_manager.get_user_opensearch_client(anonymous_user.user_id, effective_jwt)
        if hasattr(session_manager, "_anonymous_jwt"):
            effective_jwt = session_manager._anonymous_jwt

    default_tweaks = {
        "OpenSearchVectorStoreComponentMultimodalMultiEmbedding-By9U4": {
            "docs_metadata": [
                {"key": "owner", "value": None},
                {"key": "owner_name", "value": anonymous_user.name},
                {"key": "owner_email", "value": anonymous_user.email},
                {"key": "connector_type", "value": "openrag_docs"},
                {"key": "is_sample_data", "value": "true"},
            ]
        }
    }

    task_id = await task_service.create_langflow_upload_task(
        user_id=None,
        file_paths=file_paths,
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        jwt_token=effective_jwt,
        owner_name=anonymous_user.name,
        owner_email=anonymous_user.email,
        session_id=None,
        tweaks=default_tweaks,
        settings=None,
        replace_duplicates=True,
        connector_type=connector_type,
        existing_task_id=existing_task_id,
    )

    logger.info(
        "Started Langflow ingestion task for default documents",
        task_id=task_id,
        file_count=len(file_paths),
    )
    return task_id


async def _ingest_default_documents_url_langflow(
    langflow_file_service,
    session_manager,
    task_service,
    docs_url: str,
    crawl_depth: int,
    jwt_token=None,
):
    """Ingest default URL docs using the Langflow URL ingestion pipeline."""
    if not docs_url:
        raise ValueError("DEFAULT_DOCS_URL is not configured")

    logger.info(
        "Using Langflow URL ingestion pipeline for default documents",
        docs_url=docs_url,
        crawl_depth=crawl_depth,
    )

    from session_manager import AnonymousUser

    anonymous_user = AnonymousUser()
    effective_jwt = jwt_token

    if not effective_jwt and session_manager:
        session_manager.get_user_opensearch_client(anonymous_user.user_id, effective_jwt)
        if hasattr(session_manager, "_anonymous_jwt"):
            effective_jwt = session_manager._anonymous_jwt

    default_tweaks = {
        "OpenSearchVectorStoreComponentMultimodalMultiEmbedding-By9U4": {
            "docs_metadata": [
                {"key": "owner", "value": None},
                {"key": "owner_name", "value": anonymous_user.name},
                {"key": "owner_email", "value": anonymous_user.email},
                {"key": "connector_type", "value": "openrag_docs"},
                {"key": "is_sample_data", "value": "true"},
            ]
        }
    }

    task_id = await task_service.create_langflow_url_upload_task(
        owner_user_id=None,
        docs_url=docs_url,
        crawl_depth=crawl_depth,
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        jwt_token=effective_jwt,
        owner_name=anonymous_user.name,
        owner_email=anonymous_user.email,
        connector_type="openrag_docs",
        tweaks=default_tweaks,
    )

    logger.info(
        "Started Langflow URL ingestion task for default documents",
        task_id=task_id,
        docs_url=docs_url,
    )
    return task_id


async def _ingest_default_documents_url(
    document_service,
    models_service,
    docs_url: str,
    crawl_depth: int,
    jwt_token=None,
):
    """Ingest default docs from URL using OpenRAG ingestion logic (no Langflow)."""
    if not docs_url:
        raise ValueError("DEFAULT_DOCS_URL is not configured")

    logger.info(
        "Running default URL docs ingestion with OpenRAG processor",
        docs_url=docs_url,
        crawl_depth=crawl_depth,
    )
    temp_file_path = await materialize_url_as_text_file(
        docs_url=docs_url,
        crawl_depth=crawl_depth,
    )
    try:
        from models.processors import DocumentFileProcessor
        from session_manager import AnonymousUser
        from utils.hash_utils import hash_id

        anonymous_user = AnonymousUser()

        processor = DocumentFileProcessor(
            document_service,
            models_service=models_service,
            owner_user_id=None,
            jwt_token=jwt_token,
            owner_name=anonymous_user.name,
            owner_email=anonymous_user.email,
            is_sample_data=True,
            connector_type="openrag_docs",
        )
        await processor.process_document_standard(
            file_path=temp_file_path,
            file_hash=hash_id(temp_file_path),
            owner_user_id=None,
            original_filename="openrag-url-default.txt",
            jwt_token=jwt_token,
            owner_name=anonymous_user.name,
            owner_email=anonymous_user.email,
            file_size=os.path.getsize(temp_file_path),
            connector_type="openrag_docs",
            is_sample_data=True,
        )
    finally:
        try:
            os.unlink(temp_file_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(
                "Failed to clean temporary default URL docs file",
                path=temp_file_path,
                error=str(e),
            )


async def _delete_existing_default_docs(session_manager, connector_type: str, jwt_token=None):
    """Delete previously ingested default OpenRAG docs before reingestion."""
    from session_manager import AnonymousUser

    if session_manager is None:
        logger.warning(
            "Session manager unavailable; skipping default docs cleanup before reingestion"
        )
        return

    anonymous_user = AnonymousUser()
    effective_jwt = jwt_token
    if not effective_jwt and session_manager:
        session_manager.get_user_opensearch_client(anonymous_user.user_id, effective_jwt)
        if hasattr(session_manager, "_anonymous_jwt"):
            effective_jwt = session_manager._anonymous_jwt

    opensearch_client = session_manager.get_user_opensearch_client(
        anonymous_user.user_id, effective_jwt
    )
    delete_query = {
        "query": {
            "bool": {
                "should": [
                    # URL-based default docs are ingested as system_default and
                    # owned by the anonymous onboarding user.
                    {
                        "bool": {
                            "must": [
                                {"term": {"connector_type": connector_type}},
                                {"term": {"owner_email": anonymous_user.email}},
                            ]
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }
    }
    result = await opensearch_client.delete_by_query(
        index=get_index_name(),
        body=delete_query,
        conflicts="proceed",
    )
    logger.info(
        "Deleted existing default OpenRAG docs before reingestion",
        deleted_chunks=result.get("deleted", 0),
    )


async def _reingest_default_docs_on_upgrade_if_needed(
    document_service,
    models_service,
    task_service,
    langflow_file_service,
    session_manager,
    jwt_token=None,
):
    """Reingest default OpenRAG docs once when app version changes."""
    config = get_openrag_config()

    previous_version = config.onboarding.openrag_docs_ingested_version
    current_version = OPENRAG_VERSION
    should_reingest = bool(previous_version) and previous_version != current_version

    # Legacy installs may not have a stored docs ingestion version.
    # Use the presence of the OpenRAG docs filter as the signal that docs were
    # already onboarded, independent of whether config.edited is set.
    if not previous_version and config.onboarding.openrag_docs_filter_id:
        should_reingest = True

    if not should_reingest:
        return False

    logger.info(
        "Detected OpenRAG upgrade; reingesting default docs",
        previous_version=previous_version,
        current_version=current_version,
    )
    await _delete_existing_default_docs(
        session_manager, connector_type="openrag_docs", jwt_token=jwt_token
    )
    await ingest_openrag_docs_when_ready(
        document_service,
        models_service,
        task_service,
        langflow_file_service,
        session_manager,
        jwt_token=jwt_token,
    )
    config.onboarding.openrag_docs_ingested_version = current_version
    if _should_use_url_default_docs_ingest():
        # Refresh signature metadata after upgrade reingestion so startup
        # signature checks don't trigger an immediate duplicate ingest.
        config.onboarding.openrag_docs_remote_signature = await _get_remote_docs_signature(
            DEFAULT_DOCS_URL
        )
    else:
        config.onboarding.openrag_docs_remote_signature = None
    if not config_manager.save_config_file(config):
        logger.warning(
            "Default docs were reingested but failed to persist metadata",
            current_version=current_version,
            signature=config.onboarding.openrag_docs_remote_signature,
        )
    return True


async def _get_remote_docs_signature(docs_url: str):
    """Get a signature for remote docs to detect content updates."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            head_response = await client.head(docs_url)
            if head_response.status_code >= 400:
                get_response = await client.get(docs_url)
                if get_response.status_code >= 400:
                    logger.warning(
                        "Failed to fetch remote docs signature",
                        docs_url=docs_url,
                        status_code=get_response.status_code,
                    )
                    return None
                return hashlib.sha256(get_response.text.encode("utf-8")).hexdigest()

            etag = (head_response.headers.get("etag") or "").strip()
            last_modified = (head_response.headers.get("last-modified") or "").strip()
            if etag:
                # Prefer ETag when available: it is typically the strongest
                # cache validator and stays stable if extra cache headers
                # appear/disappear without content changes.
                return f"etag={etag}"
            if last_modified:
                return f"last_modified={last_modified}"

            # HEAD has no body. If cache headers are missing, fetch the page body.
            get_response = await client.get(docs_url)
            if get_response.status_code >= 400:
                logger.warning(
                    "Failed to fetch remote docs signature body fallback",
                    docs_url=docs_url,
                    status_code=get_response.status_code,
                )
                return None
            return hashlib.sha256(get_response.text.encode("utf-8")).hexdigest()
    except Exception as e:
        logger.error(
            "Unable to retrieve remote docs signature",
            docs_url=docs_url,
            error=str(e),
        )
        return None


async def refresh_default_openrag_docs(
    document_service,
    models_service,
    task_service,
    langflow_file_service,
    session_manager,
    force: bool = False,
    reason: str = "startup",
    jwt_token=None,
):
    """Refresh OpenRAG docs if remote content changed or when forced."""
    await TelemetryClient.send_event(
        Category.DOCUMENT_INGESTION,
        MessageId.ORB_DOC_REFRESH_START,
        metadata={"reason": reason, "force": force},
    )
    try:
        if not _should_use_url_default_docs_ingest():
            logger.info(
                "Skipping OpenRAG docs refresh: URL ingestion is not active",
                ingest_source=DEFAULT_DOCS_INGEST_SOURCE,
                disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW,
                has_url_ingest_flow_id=bool(LANGFLOW_URL_INGEST_FLOW_ID),
                has_docs_url=bool(DEFAULT_DOCS_URL),
            )
            await TelemetryClient.send_event(
                Category.DOCUMENT_INGESTION,
                MessageId.ORB_DOC_REFRESH_SKIPPED,
                metadata={
                    "reason": reason,
                    "force": force,
                    "skip_reason": "url_ingestion_inactive",
                },
            )
            return False

        config = get_openrag_config()
        if not config.edited:
            logger.info("Skipping OpenRAG docs refresh: onboarding not completed")
            await TelemetryClient.send_event(
                Category.DOCUMENT_INGESTION,
                MessageId.ORB_DOC_REFRESH_SKIPPED,
                metadata={
                    "reason": reason,
                    "force": force,
                    "skip_reason": "onboarding_not_completed",
                },
            )
            return False

        signature = await _get_remote_docs_signature(DEFAULT_DOCS_URL)
        if not signature and not force:
            await TelemetryClient.send_event(
                Category.DOCUMENT_INGESTION,
                MessageId.ORB_DOC_REFRESH_SKIPPED,
                metadata={
                    "reason": reason,
                    "force": force,
                    "skip_reason": "signature_unavailable",
                },
            )
            return False

        previous_signature = config.onboarding.openrag_docs_remote_signature
        should_refresh = force or (signature is not None and signature != previous_signature)
        if not should_refresh:
            logger.info(
                "OpenRAG docs refresh skipped: remote signature unchanged",
                signature=signature,
            )
            await TelemetryClient.send_event(
                Category.DOCUMENT_INGESTION,
                MessageId.ORB_DOC_REFRESH_SKIPPED,
                metadata={
                    "reason": reason,
                    "force": force,
                    "skip_reason": "signature_unchanged",
                },
            )
            return False

        logger.info(
            "Refreshing default OpenRAG docs",
            reason=reason,
            force=force,
            previous_signature=previous_signature,
            new_signature=signature,
        )
        await _delete_existing_default_docs(
            session_manager, connector_type="openrag_docs", jwt_token=jwt_token
        )
        await ingest_openrag_docs_when_ready(
            document_service,
            models_service,
            task_service,
            langflow_file_service,
            session_manager,
            jwt_token=jwt_token,
        )
        config.onboarding.openrag_docs_ingested_version = OPENRAG_VERSION
        # Keep docs version/signature metadata consistent after a refresh.
        # If signature retrieval failed, persist None explicitly instead of
        # leaving a stale previous signature value.
        config.onboarding.openrag_docs_remote_signature = signature
        if not config_manager.save_config_file(config):
            logger.warning(
                "OpenRAG docs refreshed but failed to persist metadata",
                version=config.onboarding.openrag_docs_ingested_version,
                signature=config.onboarding.openrag_docs_remote_signature,
            )
        await TelemetryClient.send_event(
            Category.DOCUMENT_INGESTION,
            MessageId.ORB_DOC_REFRESH_COMPLETE,
            metadata={"reason": reason, "force": force},
        )
        return True
    except Exception as e:
        await TelemetryClient.send_event(
            Category.DOCUMENT_INGESTION,
            MessageId.ORB_DOC_REFRESH_FAILED,
            metadata={
                "reason": reason,
                "force": force,
                "error_type": type(e).__name__,
            },
        )
        raise


async def _ingest_default_documents_openrag(
    document_service,
    models_service,
    task_service,
    file_paths,
    connector_type: str = "openrag_docs",
    existing_task_id: str = None,
    jwt_token=None,
):
    """Ingest default documents using traditional OpenRAG processor."""
    logger.info(
        "Using traditional OpenRAG ingestion for default documents",
        file_count=len(file_paths),
    )

    from models.processors import DocumentFileProcessor
    from session_manager import AnonymousUser

    anonymous_user = AnonymousUser()

    processor = DocumentFileProcessor(
        document_service,
        models_service=models_service,
        owner_user_id=None,
        jwt_token=jwt_token,
        owner_name=anonymous_user.name,
        owner_email=anonymous_user.email,
        is_sample_data=True,
        connector_type=connector_type,
    )

    task_id = await task_service.create_custom_task(
        "anonymous", file_paths, processor, existing_task_id=existing_task_id
    )
    logger.info(
        "Started traditional OpenRAG ingestion task",
        task_id=task_id,
        file_count=len(file_paths),
    )
    return task_id
