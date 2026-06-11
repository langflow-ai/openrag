import asyncio
import mimetypes
import os
import time
from typing import TYPE_CHECKING, Any

from config.settings import clients, get_embedding_model, get_index_name, get_openrag_config
from utils.document_processing import (
    extract_relevant,
    process_text_file,
    resplit_chunks_character_windows,
)
from utils.file_utils import (
    auto_cleanup_tempfile,
    clean_connector_filename,
    get_file_extension,
    get_filename_aliases,
    langflow_safe_filename_and_mimetype,
)
from utils.hash_utils import hash_id
from utils.logging_config import get_logger
from utils.opensearch_queries import build_filename_search_body

from .tasks import FileTask, TaskStatus, UploadTask

logger = get_logger(__name__)

if TYPE_CHECKING:
    from connectors.base import DocumentACL


class TaskProcessor:
    """Base class for task processors with shared processing logic"""

    def __init__(self, document_service=None, models_service=None, docling_service=None):
        self.document_service = document_service
        self.models_service = models_service
        self.docling_service = docling_service

    async def check_document_exists(
        self,
        file_hash: str,
        opensearch_client,
    ) -> bool:
        """
        Check if a document with the given hash already exists in OpenSearch.
        Consolidated hash checking for all processors.
        """
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await opensearch_client.search(
                    index=get_index_name(),
                    body={
                        "size": 1,
                        "_source": False,
                        "query": {"term": {"document_id": file_hash}},
                    },
                )
                hits = response.get("hits", {}).get("hits", [])
                return bool(hits)
            except (TimeoutError, Exception) as e:
                if attempt == max_retries - 1:
                    logger.error(
                        "OpenSearch exists check failed after retries",
                        file_hash=file_hash,
                        error=str(e),
                        attempt=attempt + 1,
                    )
                    # On final failure, assume document doesn't exist (safer to reprocess than skip)
                    logger.warning(
                        "Assuming document doesn't exist due to connection issues",
                        file_hash=file_hash,
                    )
                    return False
                else:
                    logger.warning(
                        "OpenSearch exists check failed, retrying",
                        file_hash=file_hash,
                        error=str(e),
                        attempt=attempt + 1,
                        retry_in=retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
        return False

    async def check_filename_exists(
        self,
        filename: str,
        opensearch_client,
    ) -> bool:
        """
        Check if a document with the given filename already exists in OpenSearch.
        Returns True if any chunks with this filename exist.
        """
        max_retries = 3
        retry_delay = 1.0

        candidate_filenames = get_filename_aliases(filename)
        if not candidate_filenames:
            return False
        # Keep track of aliases that still need checking across retries.
        # If one alias was already checked successfully with no hits, we avoid
        # re-querying it when another alias fails transiently.
        pending_candidates = list(candidate_filenames)
        # Retry strategy: only retry aliases that have not completed successfully.
        # This avoids re-querying aliases already checked with no hits when a later
        # alias fails transiently (e.g., timeout).

        for attempt in range(max_retries):
            try:
                i = 0
                while i < len(pending_candidates):
                    candidate = pending_candidates[i]
                    search_body = build_filename_search_body(candidate, size=1, source=False)
                    response = await opensearch_client.search(
                        index=get_index_name(), body=search_body
                    )
                    hits = response.get("hits", {}).get("hits", [])
                    if hits:
                        return True
                    # Successfully checked this alias with no hits; don't
                    # re-query it on future retries.
                    pending_candidates.pop(i)
                    continue
                return False

            except (TimeoutError, Exception) as e:
                if attempt == max_retries - 1:
                    logger.error(
                        "OpenSearch filename check failed after retries",
                        filename=filename,
                        error=str(e),
                        attempt=attempt + 1,
                    )
                    # On final failure, assume document doesn't exist (safer to reprocess than skip)
                    logger.warning(
                        "Assuming filename doesn't exist due to connection issues",
                        filename=filename,
                    )
                    return False
                else:
                    logger.warning(
                        "OpenSearch filename check failed, retrying",
                        filename=filename,
                        error=str(e),
                        attempt=attempt + 1,
                        retry_in=retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
        return False

    async def delete_document_by_filename(
        self,
        filename: str,
        opensearch_client,
        owner_user_id: str | None = None,
    ) -> None:
        """
        Delete all chunks of a document with the given filename from OpenSearch.
        """
        from config.settings import clients, get_index_name
        from utils.opensearch_delete import collect_visible_document_ids, delete_document_ids
        from utils.opensearch_queries import build_owned_filename_query

        try:
            write_client = clients.opensearch
            if write_client is None:
                raise RuntimeError("Backend OpenSearch write client is unavailable")

            deleted_count = 0
            if not owner_user_id:
                logger.warning(
                    "Skipped delete_by_filename because owner_user_id is missing",
                    filename=filename,
                )
                return

            candidate_filenames = get_filename_aliases(filename)
            if not candidate_filenames:
                logger.info(
                    "Skipped delete_by_filename because filename input is empty",
                    filename=filename,
                )
                return
            for candidate in candidate_filenames:
                document_ids = await collect_visible_document_ids(
                    opensearch_client,
                    index=get_index_name(),
                    query=build_owned_filename_query(candidate, owner_user_id),
                )
                deleted_count += await delete_document_ids(
                    write_client,
                    index=get_index_name(),
                    document_ids=document_ids,
                )
            logger.info(
                "Deleted existing document chunks", filename=filename, deleted_count=deleted_count
            )

        except Exception as e:
            logger.error("Failed to delete existing document", filename=filename, error=str(e))
            raise

    async def process_document_standard(
        self,
        file_path: str,
        file_hash: str,
        owner_user_id: str = None,
        original_filename: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        file_size: int = None,
        connector_type: str = "local",
        embedding_model: str = None,
        chunk_size: int = None,
        chunk_overlap: int = None,
        is_sample_data: bool = False,
        acl: "DocumentACL | None" = None,
        connector_file_id: str | None = None,
    ):
        """
        Standard processing pipeline for non-Langflow processors:
        docling conversion + embeddings + OpenSearch indexing.

        Args:
            embedding_model: Embedding model to use (defaults to the current
                embedding model from settings)
            chunk_size: Optional character window size for re-splitting extracted
                chunks (non-Langflow path, e.g. connector UI ``chunkSize``).
            chunk_overlap: Overlap between windows; must be less than ``chunk_size``.
            acl: DocumentACL instance with access control information
        """
        from services.document_service import chunk_texts_for_embeddings

        # Use provided embedding model or configured model.
        # get_embedding_model() returns empty string when Langflow ingest is enabled,
        # but OpenRAG processors still need a concrete embedding model.
        configured_embedding_model = get_openrag_config().knowledge.embedding_model
        embedding_model = embedding_model or configured_embedding_model or get_embedding_model()

        # Get user's OpenSearch client with JWT for OIDC auth
        opensearch_client = self.document_service.session_manager.get_user_opensearch_client(
            owner_user_id, jwt_token
        )

        # Check if already exists
        if await self.check_document_exists(file_hash, opensearch_client):
            return {"status": "unchanged", "id": file_hash}

        logger.info(
            "Processing document with embedding model",
            embedding_model=embedding_model,
            file_hash=file_hash,
        )

        # Check if this is a .txt or .md file - use simple processing instead of docling
        file_ext = os.path.splitext(file_path)[1].lower()

        if file_ext in (".txt", ".md"):
            # Simple text file processing without docling
            logger.info(
                "Processing as plain text file (bypassing docling)",
                file_path=file_path,
                file_hash=file_hash,
            )
            slim_doc = process_text_file(file_path)
        else:
            full_doc = await self.docling_service.convert_file(
                file_path, user_id=owner_user_id, auth_header=jwt_token
            )
            slim_doc = extract_relevant(full_doc)

        # Override filename with original_filename if provided
        if original_filename:
            slim_doc["filename"] = original_filename

        if chunk_size is not None:
            try:
                cs = int(chunk_size)
            except (TypeError, ValueError):
                cs = 0
            if cs > 0:
                try:
                    co = int(chunk_overlap) if chunk_overlap is not None else 0
                except (TypeError, ValueError):
                    co = 0
                if co < cs:
                    slim_doc["chunks"] = resplit_chunks_character_windows(
                        slim_doc["chunks"], cs, max(0, co)
                    )

        # Filter out chunks with empty or whitespace-only text before generating embeddings.
        # This ensures the length of chunks matches the length of the embeddings array,
        # since chunk_texts_for_embeddings also drops empty texts.
        slim_doc["chunks"] = [c for c in slim_doc["chunks"] if c.get("text") and c["text"].strip()]
        texts = [c["text"] for c in slim_doc["chunks"]]

        litellm_embedding_model = (
            await self.models_service.get_litellm_model_name(embedding_model)
            if self.models_service is not None
            else embedding_model
        )

        # Split into batches to avoid token limits (8191 limit, use 8000 with buffer or 2000 if it's ollama)
        if "ollama" in litellm_embedding_model:
            text_batches = chunk_texts_for_embeddings(texts, max_tokens=2000)
        else:
            text_batches = chunk_texts_for_embeddings(texts, max_tokens=8000)
        embeddings = []

        for batch in text_batches:
            resp = await clients.patched_embedding_client.embeddings.create(
                model=litellm_embedding_model, input=batch
            )
            embeddings.extend(
                [d["embedding"] if isinstance(d, dict) else d.embedding for d in resp.data]
            )

        if not embeddings or len(embeddings) == 0:
            logger.error(
                "No embeddings generated — document may be empty or unreadable",
                file_hash=file_hash,
                embedding_model=embedding_model,
            )
            return {"status": "error", "error": "No text content could be extracted from document"}

        from services.document_index_writer import (
            DocumentIndexChunk,
            DocumentIndexContext,
            DocumentIndexWriter,
        )

        document_index_writer = getattr(self.document_service, "document_index_writer", None)
        if document_index_writer is None:
            document_index_writer = DocumentIndexWriter()

        # Clear stale chunks from a prior indexing of this document. Chunks are
        # stored under ids {file_hash}_{i}; if the new chunk count is lower
        # than the prior one, trailing chunks would otherwise survive the
        # writer's idempotent upsert.
        # DLS-safe: enumerate visible chunk ids with the scoped user client,
        # then delete concrete ids with the trusted backend client.
        try:
            from utils.opensearch_delete import (
                collect_visible_document_ids,
                delete_document_ids,
            )

            write_client = clients.opensearch
            if write_client is None:
                raise RuntimeError("Backend OpenSearch write client is unavailable")

            stale_chunk_ids = await collect_visible_document_ids(
                opensearch_client,
                index=get_index_name(),
                query={"term": {"document_id": file_hash}},
            )
            await delete_document_ids(
                write_client,
                index=get_index_name(),
                document_ids=stale_chunk_ids,
                refresh=True,
            )
        except Exception as e:
            logger.warning(
                "Failed to clear stale chunks before re-index; proceeding",
                file_hash=file_hash,
                error=str(e),
            )

        # Owner is always the authenticated uploading/syncing user. Upstream ACL
        # owners/authors only contribute read access through allowed principals.
        owner = owner_user_id
        if acl:
            allowed_users = acl.allowed_users or []
            allowed_groups = acl.allowed_groups or []
            allowed_principals = acl.allowed_principals or []
            allowed_principal_labels = acl.allowed_principal_labels or []
        else:
            allowed_users = []
            allowed_groups = []
            allowed_principals = []
            allowed_principal_labels = []

        filename = original_filename if original_filename else slim_doc["filename"]
        index_context = DocumentIndexContext(
            document_id=file_hash,
            filename=filename,
            mimetype=slim_doc["mimetype"],
            embedding_model=embedding_model,
            owner=owner,
            owner_name=owner_name,
            owner_email=owner_email,
            file_size=file_size,
            connector_type=connector_type,
            allowed_users=allowed_users,
            allowed_groups=allowed_groups,
            allowed_principals=allowed_principals,
            allowed_principal_labels=allowed_principal_labels,
            is_sample_data=is_sample_data,
        )
        index_chunks = [
            DocumentIndexChunk(
                chunk_id=f"{file_hash}_{i}",
                text=chunk["text"],
                vector=vect,
                page=chunk["page"],
                metadata={"connector_file_id": connector_file_id} if connector_file_id else {},
            )
            for i, (chunk, vect) in enumerate(zip(slim_doc["chunks"], embeddings, strict=True))
        ]
        await document_index_writer.index_chunks(index_context, index_chunks, final=True)
        return {"status": "indexed", "id": file_hash}

    async def process_item(self, upload_task: UploadTask, item: Any, file_task: FileTask) -> None:
        """
        Process a single item in the task.

        This is a base implementation that should be overridden by subclasses.
        When TaskProcessor is used directly (not via subclass), this method
        is not called - only the utility methods like process_document_standard
        are used.

        Args:
            upload_task: The overall upload task
            item: The item to process (could be file path, file info, etc.)
            file_task: The specific file task to update
        """
        raise NotImplementedError(
            "process_item should be overridden by subclasses when used in task processing"
        )


class DocumentFileProcessor(TaskProcessor):
    """Default processor for regular file uploads"""

    def __init__(
        self,
        document_service,
        models_service,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        is_sample_data: bool = False,
        connector_type: str = "local",
        docling_service=None,
        replace_duplicates: bool = False,
        session_manager=None,
        settings: dict | None = None,
    ):
        super().__init__(
            document_service,
            models_service,
            docling_service=docling_service
            or (document_service.docling_service if document_service else None),
        )
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.is_sample_data = is_sample_data
        self.connector_type = connector_type
        self.replace_duplicates = replace_duplicates
        self.session_manager = session_manager or (
            document_service.session_manager if document_service else None
        )
        self.settings = settings
        if self.session_manager is None:
            raise ValueError("session_manager is required for DocumentFileProcessor")

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Process a regular file path using consolidated methods"""
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            # Use the ORIGINAL filename stored in file_task (not the transformed temp path)
            # This ensures we check/store the original filename with spaces, etc.
            original_filename = file_task.filename or os.path.basename(item)

            # Check if document with same filename already exists
            if self.session_manager is None:
                raise ValueError("session_manager is required to get OpenSearch client")
            opensearch_client = self.session_manager.get_user_opensearch_client(
                self.owner_user_id, self.jwt_token
            )

            filename_exists = await self.check_filename_exists(original_filename, opensearch_client)

            if filename_exists and not self.replace_duplicates:
                # Duplicate exists and user hasn't confirmed replacement
                file_task.status = TaskStatus.FAILED
                file_task.error = f"File with name '{original_filename}' already exists"
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
                return
            elif filename_exists and self.replace_duplicates:
                # Delete existing document before uploading new one
                logger.info(f"Replacing existing document: {original_filename}")
                await self.delete_document_by_filename(original_filename, opensearch_client)
                # Refresh index to make deletion visible before processing.
                # refresh is index-wide (indices:admin/refresh) and cannot be DLS-scoped,
                # so it must run under the admin/service client, not the user client.
                from config.settings import get_index_name

                try:
                    await clients.opensearch.indices.refresh(index=get_index_name())
                except Exception as refresh_error:
                    logger.warning(
                        "Failed to refresh index after delete",
                        error=str(refresh_error),
                    )

            # Compute hash
            file_hash = hash_id(item)

            # Get file size
            try:
                file_size = os.path.getsize(item)
            except Exception:
                file_size = 0

            # Parse ACL from settings if present
            from connectors.base import DocumentACL

            acl = None
            if self.settings and (
                self.settings.get("allowed_users") is not None
                or self.settings.get("allowed_groups") is not None
            ):
                acl = DocumentACL(
                    owner=self.owner_user_id,
                    allowed_users=self.settings.get("allowed_users", []),
                    allowed_groups=self.settings.get("allowed_groups", []),
                )

            standard_kwargs: dict[str, Any] = {}
            if self.settings:
                s = self.settings
                em = s.get("embeddingModel")
                if isinstance(em, str) and em.strip():
                    standard_kwargs["embedding_model"] = em.strip()
                for ui_key, param in (
                    ("chunkSize", "chunk_size"),
                    ("chunkOverlap", "chunk_overlap"),
                ):
                    raw = s.get(ui_key)
                    if raw is not None:
                        try:
                            standard_kwargs[param] = int(raw)
                        except (TypeError, ValueError):
                            pass

            # Use consolidated standard processing
            result = await self.process_document_standard(
                file_path=item,
                file_hash=file_hash,
                owner_user_id=self.owner_user_id,
                original_filename=original_filename,
                jwt_token=self.jwt_token,
                owner_name=self.owner_name,
                owner_email=self.owner_email,
                file_size=file_size,
                connector_type=self.connector_type,
                is_sample_data=self.is_sample_data,
                acl=acl,
                **standard_kwargs,
            )

            if result.get("status") == "error":
                file_task.status = TaskStatus.FAILED
                file_task.error = result.get("error", "Failed to process document")
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
            else:
                file_task.status = TaskStatus.COMPLETED
                file_task.result = result
                file_task.updated_at = time.time()
                upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise


class ConnectorFileProcessor(TaskProcessor):
    """Processor for connector file uploads"""

    def __init__(
        self,
        connector_service,
        connection_id: str,
        files_to_process: list,
        user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        document_service=None,
        models_service=None,
        ingest_settings: dict[str, Any] | None = None,
        replace_duplicates: bool = False,
    ):
        super().__init__(
            document_service=document_service,
            models_service=models_service,
            docling_service=document_service.docling_service if document_service else None,
        )
        self.connector_service = connector_service
        self.connection_id = connection_id
        self.files_to_process = files_to_process
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.ingest_settings = ingest_settings
        self.replace_duplicates = replace_duplicates

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Process a connector file using unified methods"""
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            file_id = item  # item is the connector file ID

            # Get the connector and connection info
            connector = await self.connector_service.get_connector(self.connection_id)
            connection = await self.connector_service.connection_manager.get_connection(
                self.connection_id
            )
            if not connector or not connection:
                raise ValueError(f"Connection '{self.connection_id}' not found")

            # Validate file extension early if filename is available
            VALID_EXTENSIONS = {
                "adoc",
                "asciidoc",
                "asc",
                "bmp",
                "csv",
                "dotx",
                "dotm",
                "docm",
                "docx",
                "htm",
                "html",
                "jpeg",
                "jpg",
                "md",
                "pdf",
                "png",
                "potx",
                "ppsx",
                "pptm",
                "potm",
                "ppsm",
                "pptx",
                "tiff",
                "txt",
                "xls",
                "xlsx",
                "xhtml",
                "webp",
            }
            if file_task.filename:
                ext = file_task.filename.split(".")[-1].lower() if "." in file_task.filename else ""
                if ext not in VALID_EXTENSIONS:
                    file_task.status = TaskStatus.FAILED
                    file_task.error = f"The file '{file_task.filename}' has an incompatible type."
                    file_task.updated_at = time.time()
                    upload_task.failed_files += 1
                    return

            # Get file content from connector
            try:
                document = await connector.get_file_content(file_id)
            except (FileNotFoundError, ValueError) as e:
                msg = str(e).lower()
                if "not found" in msg or "404" in msg:
                    # File gone at source — remove indexed chunks by document_id
                    # (= connector file_id) so it stops appearing in search/chat.
                    # Filename rename (e.g. .txt → .md) is irrelevant here.
                    deleted_chunks = 0
                    try:
                        from api.documents import delete_chunks_by_document_ids

                        opensearch_client = (
                            self.document_service.session_manager.get_user_opensearch_client(
                                self.user_id, self.jwt_token
                            )
                        )
                        deleted_chunks = await delete_chunks_by_document_ids(
                            [file_id], opensearch_client, get_index_name()
                        )
                    except Exception as cleanup_err:
                        logger.error(
                            "Failed to clean up chunks for deleted source file",
                            file_id=file_id,
                            connection_id=self.connection_id,
                            error=str(cleanup_err),
                        )

                    logger.warning(
                        "File no longer exists at source — removed from index",
                        file_id=file_id,
                        connection_id=self.connection_id,
                        deleted_chunks=deleted_chunks,
                        error=str(e),
                    )
                    file_task.status = TaskStatus.SKIPPED
                    file_task.result = {
                        "status": "skipped",
                        "reason": "deleted_at_source",
                        "deleted_chunks": deleted_chunks,
                    }
                    file_task.updated_at = time.time()
                    upload_task.successful_files += 1
                    return
                raise

            # Update filename in task once we have it from the connector
            file_task.filename = clean_connector_filename(document.filename, document.mimetype)

            # Re-check filename validation
            name = file_task.filename or document.filename or ""
            ext = name.split(".")[-1].lower() if "." in name else ""
            if ext not in VALID_EXTENSIONS:
                file_task.status = TaskStatus.FAILED
                file_task.error = f"The file '{name}' has an incompatible type."
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
                return

            if not self.user_id:
                raise ValueError("user_id not provided to ConnectorFileProcessor")

            opensearch_client = self.document_service.session_manager.get_user_opensearch_client(
                self.user_id, self.jwt_token
            )
            if await self.check_filename_exists(document.filename, opensearch_client):
                if not self.replace_duplicates:
                    file_task.status = TaskStatus.SKIPPED
                    file_task.error = None
                    file_task.result = {
                        "status": "skipped",
                        "reason": "duplicate_filename",
                        "warning": "A file with this name already exists.",
                    }
                    file_task.updated_at = time.time()
                    upload_task.successful_files += 1
                    return
                await self.delete_document_by_filename(
                    document.filename,
                    opensearch_client,
                    owner_user_id=self.user_id,
                )

            # Create temporary file from document content
            suffix = os.path.splitext(document.filename)[1]
            if not suffix:
                suffix = get_file_extension(document.mimetype)
            with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
                # Write content to temp file
                with open(tmp_path, "wb") as f:
                    f.write(document.content)

                # Compute hash
                file_hash = hash_id(tmp_path)

                if await self.check_document_exists(file_hash, opensearch_client):
                    file_task.status = TaskStatus.COMPLETED
                    file_task.result = {"status": "unchanged", "id": file_hash}
                    file_task.updated_at = time.time()
                    upload_task.successful_files += 1
                    return

                from config.settings import DISABLE_INGEST_WITH_LANGFLOW

                if (
                    not DISABLE_INGEST_WITH_LANGFLOW
                    and self.connector_service.langflow_service is not None
                ):
                    # Delete existing chunks for this document before Langflow re-ingestion
                    try:
                        from utils.opensearch_delete import (
                            collect_visible_document_ids,
                            delete_document_ids,
                        )

                        chunk_ids = await collect_visible_document_ids(
                            opensearch_client,
                            index=get_index_name(),
                            query={"term": {"document_id": document.id}},
                        )
                        deleted_count = await delete_document_ids(
                            opensearch_client,
                            index=get_index_name(),
                            document_ids=chunk_ids,
                            refresh=True,
                        )
                        logger.info(
                            "Deleted existing chunks before Langflow re-ingestion",
                            document_id=document.id,
                            deleted_count=deleted_count,
                        )
                    except Exception as delete_err:
                        logger.warning(
                            "Failed to delete existing chunks before Langflow re-ingestion",
                            document_id=document.id,
                            error=str(delete_err),
                        )

                    # Ingest via unified Langflow pipeline (two-phase Docling + Langflow run)
                    langflow_filename, processed_mimetype = langflow_safe_filename_and_mimetype(
                        document.filename, document.mimetype
                    )
                    file_tuple = (langflow_filename, document.content, processed_mimetype)

                    # Extract ACL information
                    allowed_users: list[str] = []
                    allowed_groups: list[str] = []
                    if document.acl:
                        try:
                            allowed_users = document.acl.allowed_users or []
                            allowed_groups = document.acl.allowed_groups or []
                        except AttributeError:
                            pass

                    # Prepare tweaks
                    connector_tweak_settings = None
                    if isinstance(self.ingest_settings, dict):
                        connector_tweak_settings = dict(self.ingest_settings)
                        connector_tweak_settings.pop("embeddingModel", None)

                    tweaks = self.connector_service.langflow_service.merge_ui_ingest_settings_into_tweaks(
                        {}, connector_tweak_settings
                    )

                    result = await self.connector_service.langflow_service.upload_and_ingest_file(
                        file_tuple=file_tuple,
                        session_id=None,
                        tweaks=tweaks,
                        settings=self.ingest_settings,
                        jwt_token=self.jwt_token,
                        owner=self.user_id,
                        owner_name=self.owner_name,
                        owner_email=self.owner_email,
                        connector_type=connection.connector_type,
                        docling_polling_service=self.connector_service.task_service.docling_polling_service
                        if self.connector_service.task_service
                        else None,
                        file_task=file_task,
                        document_id=document.id,
                        source_url=document.source_url,
                        allowed_users=allowed_users,
                        allowed_groups=allowed_groups,
                    )
                    # Langflow returns "success" even when no text was extracted
                    # (e.g. image files without OCR). Verify the document actually
                    # landed in OpenSearch before declaring success.
                    if not await self.check_document_exists(document.id, opensearch_client):
                        result = {
                            "status": "error",
                            "error": "No text content could be extracted from document",
                        }
                else:
                    # Standard OpenRAG processing pipeline (process_document_standard)
                    standard_kwargs: dict[str, Any] = {}
                    if isinstance(self.ingest_settings, dict):
                        s = self.ingest_settings
                        em = s.get("embeddingModel")
                        if isinstance(em, str) and em.strip():
                            standard_kwargs["embedding_model"] = em.strip()
                        for ui_key, param in (
                            ("chunkSize", "chunk_size"),
                            ("chunkOverlap", "chunk_overlap"),
                        ):
                            raw = s.get(ui_key)
                            if raw is not None:
                                try:
                                    standard_kwargs[param] = int(raw)
                                except (TypeError, ValueError):
                                    pass

                    result = await self.process_document_standard(
                        file_path=tmp_path,
                        file_hash=file_hash,
                        owner_user_id=self.user_id,
                        original_filename=document.filename,
                        jwt_token=self.jwt_token,
                        owner_name=self.owner_name,
                        owner_email=self.owner_email,
                        file_size=len(document.content),
                        connector_type=connection.connector_type,
                        acl=document.acl,
                        connector_file_id=document.id,
                        **standard_kwargs,
                    )

                    # Update indexed chunks with connector-specific metadata
                    if result["status"] in ["indexed", "unchanged"]:
                        await self.connector_service._update_connector_metadata(
                            document,
                            self.user_id,
                            connection.connector_type,
                            self.jwt_token,
                            id_field="connector_file_id",
                        )

                    # Add connector-specific metadata
                    result.update(
                        {
                            "source_url": document.source_url,
                            "document_id": document.id,
                        }
                    )

            if result.get("status") == "error":
                file_task.status = TaskStatus.FAILED
                file_task.error = result.get("error", "Failed to process document")
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
            else:
                file_task.status = TaskStatus.COMPLETED
                file_task.result = result
                file_task.updated_at = time.time()
                upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise


class S3FileProcessor(TaskProcessor):
    """Processor for files stored in S3 buckets"""

    def __init__(
        self,
        document_service,
        bucket: str,
        s3_client=None,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        models_service=None,
        docling_service=None,
    ):
        import boto3

        super().__init__(
            document_service,
            models_service,
            docling_service,
        )
        self.bucket = bucket
        self.s3_client = s3_client or boto3.client("s3")
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Download an S3 object and process it using DocumentService"""
        import time

        from models.tasks import TaskStatus

        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            suffix = os.path.splitext(item)[1]
            with auto_cleanup_tempfile(suffix=suffix) as tmp_path:
                # Download object to temporary file
                with open(tmp_path, "wb") as tmp_file:
                    self.s3_client.download_fileobj(self.bucket, item, tmp_file)

                # Compute hash
                file_hash = hash_id(tmp_path)

                # Get object size
                try:
                    obj_info = self.s3_client.head_object(Bucket=self.bucket, Key=item)
                    file_size = obj_info.get("ContentLength", 0)
                except Exception:
                    file_size = 0

                # Use consolidated standard processing
                result = await self.process_document_standard(
                    file_path=tmp_path,
                    file_hash=file_hash,
                    owner_user_id=self.owner_user_id,
                    original_filename=item,  # Use S3 key as filename
                    jwt_token=self.jwt_token,
                    owner_name=self.owner_name,
                    owner_email=self.owner_email,
                    file_size=file_size,
                    connector_type="s3",
                )

                result["path"] = f"s3://{self.bucket}/{item}"
                if result.get("status") == "error":
                    file_task.status = TaskStatus.FAILED
                    file_task.error = result.get("error", "Failed to process document")
                    upload_task.failed_files += 1
                else:
                    file_task.status = TaskStatus.COMPLETED
                    file_task.result = result
                    upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            upload_task.failed_files += 1
        finally:
            file_task.updated_at = time.time()


class LangflowFileProcessor(TaskProcessor):
    """Processor for Langflow file uploads with two-phase Docling + Langflow ingestion."""

    def __init__(
        self,
        langflow_file_service,
        session_manager,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        session_id: str = None,
        tweaks: dict = None,
        settings: dict = None,
        replace_duplicates: bool = False,
        connector_type: str = "local",
        docling_polling_service=None,
    ):
        super().__init__()
        self.langflow_file_service = langflow_file_service
        self.session_manager = session_manager
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.session_id = session_id
        self.tweaks = tweaks or {}
        self.settings = settings
        self.replace_duplicates = replace_duplicates
        self.connector_type = connector_type
        # Backend-side Docling polling coordinator. Injected by TaskService
        # from the container; gating by ENABLE_BACKEND_DOCLING_POLLING happens
        # at construction time in app.container. When None, the legacy
        # single-call ingestion path is used.
        self.docling_polling_service = docling_polling_service

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        """Process a file path using LangflowFileService upload_and_ingest_file"""
        # Update task status
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            # Use the ORIGINAL filename stored in file_task (not the transformed temp path)
            # This ensures we check/store the original filename with spaces, etc.
            original_filename = file_task.filename or os.path.basename(item)

            # Check if document with same filename already exists
            opensearch_client = self.session_manager.get_user_opensearch_client(
                self.owner_user_id, self.jwt_token
            )

            filename_exists = await self.check_filename_exists(original_filename, opensearch_client)

            if filename_exists and not self.replace_duplicates:
                # Duplicate exists and user hasn't confirmed replacement
                file_task.status = TaskStatus.FAILED
                file_task.error = f"File with name '{original_filename}' already exists"
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
                return
            elif filename_exists and self.replace_duplicates:
                # Delete existing document before uploading new one
                logger.info(f"Replacing existing document: {original_filename}")
                await self.delete_document_by_filename(
                    original_filename,
                    opensearch_client,
                    owner_user_id=self.owner_user_id,
                )
                # Refresh index to make deletion visible before processing.
                # refresh is index-wide (indices:admin/refresh) and cannot be DLS-scoped,
                # so it must run under the admin/service client, not the user client.
                try:
                    await clients.opensearch.indices.refresh(index=get_index_name())
                except Exception as refresh_error:
                    logger.warning(
                        "Failed to refresh index after delete",
                        error=str(refresh_error),
                    )

            # Read file content for processing
            with open(item, "rb") as f:
                content = f.read()

            # Create file tuple for upload using ORIGINAL filename
            # This ensures the document is indexed with the original name
            content_type, _ = mimetypes.guess_type(original_filename)
            if not content_type:
                content_type = "application/octet-stream"

            # Langflow's docling chokes on text/plain — rename .txt -> .md.
            langflow_filename, content_type = langflow_safe_filename_and_mimetype(
                original_filename, content_type
            )
            file_tuple = (langflow_filename, content, content_type)

            effective_jwt = self.jwt_token
            if self.session_manager and not effective_jwt:
                effective_jwt = self.session_manager.get_effective_jwt_token(
                    self.owner_user_id,
                    None,
                )

            # Prepare metadata tweaks similar to API endpoint
            final_tweaks = self.tweaks.copy() if self.tweaks else {}

            # Process file using langflow service. Passing the polling
            # service triggers the two-phase model: backend polls Docling,
            # then invokes Langflow only after SUCCESS. file_task is passed
            # so phase / docling_status are tracked on the task record.
            result = await self.langflow_file_service.upload_and_ingest_file(
                file_tuple=file_tuple,
                session_id=self.session_id,
                tweaks=final_tweaks,
                settings=self.settings,
                jwt_token=effective_jwt,
                owner=self.owner_user_id,
                owner_name=self.owner_name,
                owner_email=self.owner_email,
                connector_type=self.connector_type,
                docling_polling_service=self.docling_polling_service,
                file_task=file_task,
            )

            # Langflow returns "success" even when no text was extracted.
            # Verify the document actually landed in OpenSearch.
            file_hash = hash_id(item)
            if not await self.check_document_exists(file_hash, opensearch_client):
                file_task.status = TaskStatus.FAILED
                file_task.error = "No text content could be extracted from document"
                file_task.updated_at = time.time()
                upload_task.failed_files += 1
            else:
                # Update task with success
                file_task.status = TaskStatus.COMPLETED
                file_task.result = result
                file_task.updated_at = time.time()
                upload_task.successful_files += 1

        except Exception as e:
            # Update task with failure
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise
