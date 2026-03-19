import asyncio
import logging
import os
from typing import Any, cast

from openrag_sdk import OpenRAGClient
from openrag_sdk.models import IngestResponse, IngestTaskStatus, SettingsUpdateOptions
from pydantic import BaseModel, Field
from ragworkbench import RagDataLoader
from ragworkbench.api.ingest import IngestParams, IngestPipeline
from ragworkbench.api.ingest_artifact import IngestArtifact
from ragworkbench.boards.board_registry import ingest_pipeline
from ragworkbench.datasets_loader.data_models.rag_corpus import RagCorpus

logger = logging.getLogger(__name__)


class ChunkingParams(BaseModel):
    """Parameters for document chunking."""

    chunk_size: int = Field(default=512, description="Size of each chunk")
    chunk_overlap: int = Field(default=50, description="Overlap between chunks")


class EmbeddingModelParams(BaseModel):
    """Parameters for embedding model."""

    model_id: str = Field(description="Embedding model identifier")


class OpenRAGIngestParams(IngestParams):
    """Parameters for OpenRAG ingestion pipeline."""

    embedding_model: EmbeddingModelParams = Field(
        description="Embedding model configuration"
    )
    chunking: ChunkingParams | None = Field(
        default=None, description="Chunking configuration"
    )
    timeout: float = Field(
        default=300.0,
        description="HTTP request timeout in seconds (default: 5 minutes)",
    )


class OpenRAGIngestArtifact(IngestArtifact):
    """Artifact returned after OpenRAG ingestion."""

    index_name: str = Field(description="Name of the created index")


@ingest_pipeline(name="openrag", params_class=OpenRAGIngestParams)
class OpenRAGIngest(IngestPipeline):
    """Ingestion pipeline for OpenRAG backend."""

    def __init__(self, params: OpenRAGIngestParams) -> None:
        super().__init__(params)
        self.params: OpenRAGIngestParams = params

    def process(
        self,
        data_loader: RagDataLoader,
    ) -> list[IngestArtifact]:
        """
        Process documents through OpenRAG ingestion pipeline.

        Args:
            data_loader: Data loader providing the corpus to ingest

        Returns:
            List containing a single OpenRAGIngestArtifact with ingestion details
        """
        logger.info("Starting OpenRAG ingestion process")

        # Get corpus from data loader
        rag_corpus = data_loader.get_corpus()

        # Generate index name based on corpus and configuration
        index_name = self._get_index_name(rag_corpus)

        # Run async operations
        asyncio.run(self._async_process(rag_corpus, index_name))

        logger.info(f"OpenRAG ingestion completed. Index name: {index_name}")

        return [
            OpenRAGIngestArtifact(
                index_name=index_name,
            )
        ]

    async def _async_process(self, rag_corpus: RagCorpus, index_name: str) -> None:
        """Async processing of ingestion pipeline."""
        # Initialize SDK client with configured timeout (URL from environment)
        async with OpenRAGClient(timeout=self.params.timeout) as sdk_client:
            # Update settings with index name and chunking configuration (using SDK)
            await self._update_settings(sdk_client, index_name)

            # Onboard with embedding model (using SDK)
            await self._onboard(sdk_client)

            # Ingest the corpus (using SDK)
            await self._ingest_corpus_with_retries(sdk_client, rag_corpus)

    async def _update_settings(
        self, sdk_client: OpenRAGClient, index_name: str
    ) -> None:
        """Update OpenRAG settings with chunking and index configuration using SDK."""
        logger.info(f"Updating settings for index: '{index_name}'")

        # Build settings update options
        settings_dict: dict[str, Any] = {
            "embedding_model": self.params.embedding_model.model_id,
            "index_name": index_name,
        }

        if self.params.chunking:
            settings_dict["chunk_size"] = self.params.chunking.chunk_size
            settings_dict["chunk_overlap"] = self.params.chunking.chunk_overlap

        # Use SDK to update settings
        options = SettingsUpdateOptions(**settings_dict)
        logger.info(f"Updating settings to {options}..")
        await sdk_client.settings.update(options)
        logger.info("Settings update completed.")

    async def _onboard(self, sdk_client: OpenRAGClient) -> None:
        """Onboard with embedding model configuration using SDK.

        Args:
            sdk_client: The OpenRAG SDK client
        """
        logger.info("Onboarding with embedding model")

        await sdk_client.onboarding.onboarding(
            embedding_model=self.params.embedding_model.model_id,
        )

    async def _ingest_corpus_with_retries(
        self, sdk_client: OpenRAGClient, rag_corpus: RagCorpus
    ) -> None:
        """
        Ingest corpus documents into OpenRAG with retry mechanism.

        Raises:
            RuntimeError: If ingestion fails after max_attempts retry attempts
        """
        max_attempts = 3
        attempt = 1
        while attempt <= max_attempts:
            logger.info(f"Ingestion attempt {attempt}/{max_attempts}")
            num_failures = await self._ingest_corpus(sdk_client, rag_corpus)

            if num_failures == 0:
                logger.info("Ingest corpus completed successfully.")
                return

            # If there were failures but not the last attempt, retry
            if attempt < max_attempts:
                logger.warning(
                    f"Ingestion attempt {attempt} had {num_failures} batch failures. Retrying..."
                )
                attempt += 1
            else:
                # Last attempt failed
                raise RuntimeError(
                    f"Unable to ingest corpus after {max_attempts} attempts, num_failures = {num_failures}."
                )

    async def _ingest_corpus(
        self, sdk_client: OpenRAGClient, rag_corpus: RagCorpus
    ) -> int:
        """
        Implementation of corpus ingestion logic using SDK.

        Returns:
            Number of batch failures
        """
        documents = rag_corpus.documents
        logger.info(f"Checking which of {len(documents)} documents need ingestion")

        # Filter out documents already in index
        documents_not_in_index = [
            document
            for document in documents
            if not await sdk_client.documents.filename_exists(document.name)
        ]

        num_documents_to_index = len(documents_not_in_index)
        if num_documents_to_index == 0:
            logger.info(
                f"All {len(documents)} documents already in index, skipping ingestion"
            )
            return 0

        logger.info(f"Ingesting {num_documents_to_index}/{len(documents)} documents")

        # Ingest documents one by one using SDK
        num_failures = 0
        for i, document in enumerate(documents_not_in_index, start=1):
            logger.info(
                f"Ingesting document {i}/{num_documents_to_index}: {document.name}"
            )
            try:
                # Reset stream position before ingestion
                document.stream.seek(0)

                # Use SDK's ingest method with wait=True
                # Returns IngestTaskStatus when wait=True
                result: IngestResponse | IngestTaskStatus = (
                    await sdk_client.documents.ingest(
                        file=document.stream,
                        filename=document.name,
                        wait=True,
                        poll_interval=30.0,
                        timeout=60.0 * 20,  # 20 minutes
                    )
                )

                # Cast to IngestTaskStatus since wait=True
                task_status = cast(IngestTaskStatus, result)

                # Check if ingestion was successful
                if task_status.status == "failed" or task_status.failed_files > 0:
                    logger.error(
                        f"Failed to ingest {document.name}: "
                        f"status={task_status.status}, "
                        f"failed_files={task_status.failed_files}/{task_status.total_files}"
                    )
                    num_failures += 1
                else:
                    logger.info(
                        f"Successfully ingested {document.name}: "
                        f"processed={task_status.processed_files}/{task_status.total_files}"
                    )
            except Exception as e:
                logger.error(f"Error ingesting {document.name}: {e}")
                num_failures += 1

        return num_failures

    def _get_index_name(self, rag_corpus: RagCorpus) -> str:
        """Generate a unique index name based on corpus and configuration."""
        import hashlib
        import json

        file_names = [document.name for document in rag_corpus.documents]
        file_names_sorted = sorted(file_names)

        chunking_dump = ""
        if self.params.chunking:
            chunking_dump = self.params.chunking.model_dump_json()

        index_config = {
            "chunking": chunking_dump,
            "embedding_model": self.params.embedding_model.model_dump_json(),
            "files_names": file_names_sorted,
        }

        config_str = json.dumps(index_config, sort_keys=True)
        index_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]

        # Prefix must be documents to be consistent with OpenRAG index permissions
        index_name = f"documents_{index_hash}"
        return index_name
