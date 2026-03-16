"""OpenRAG inference pipeline implementation for ragbench."""

import asyncio
import logging
import traceback
from typing import Any

from openrag_sdk import ContentEvent, DoneEvent, OpenRAGClient, SourcesEvent
from openrag_sdk.models import SettingsUpdateOptions
from pydantic import BaseModel, Field
from ragworkbench.api.inference import InferenceParams, InferencePipeline
from ragworkbench.api.inference_result import InferenceResult, Trajectory
from ragworkbench.api.ingest_artifact import IngestArtifact
from ragworkbench.boards.board_registry import inference_pipeline
from ragworkbench.datasets_loader.data_models import RagBenchmarkEntry

from openrag_eval.pipelines.ingest import OpenRAGIngestArtifact

logger = logging.getLogger(__name__)


class GenerativeModelParams(BaseModel):
    """Parameters for generative model configuration."""

    provider_id: str = Field(
        description="LLM provider identifier (e.g., 'anthropic', 'openai')"
    )
    model_id: str = Field(
        description="Model identifier (e.g., 'claude-3-5-sonnet-20241022')"
    )


class OpenRAGInferenceParams(InferenceParams):
    """Parameters for OpenRAG inference pipeline."""

    generative_model: GenerativeModelParams = Field(
        description="Generative model configuration"
    )
    batch_size: int = Field(
        default=5, description="Number of parallel inference requests"
    )
    timeout: float = Field(
        default=300.0,
        description="HTTP request timeout in seconds (default: 5 minutes)",
    )


@inference_pipeline(name="openrag", params_class=OpenRAGInferenceParams)
class OpenRAGInference(InferencePipeline):
    """Inference pipeline for OpenRAG backend."""

    def __init__(
        self,
        params: OpenRAGInferenceParams,
        cache_dir: str | None = None,
    ) -> None:
        """
        Initialize OpenRAG inference pipeline.

        Args:
            params: OpenRAG inference parameters
            cache_dir: Optional directory for caching generation results
        """
        super().__init__(params, cache_dir=cache_dir)
        self.params: OpenRAGInferenceParams = params
        self._ingest_artifact: OpenRAGIngestArtifact | None = None

    def set_ingest_artifacts(self, ingest_artifacts: list[IngestArtifact]) -> None:
        """
        Set the ingest artifacts from the ingestion pipeline.

        Args:
            ingest_artifacts: List of ingest artifacts (expects single OpenRAGIngestArtifact)
        """
        if len(ingest_artifacts) != 1:
            raise ValueError(
                f"Expected exactly 1 ingest artifact, got {len(ingest_artifacts)}"
            )

        artifact = ingest_artifacts[0]
        if not isinstance(artifact, OpenRAGIngestArtifact):
            raise TypeError(
                f"Expected OpenRAGIngestArtifact, got {type(artifact).__name__}"
            )

        self._ingest_artifact = artifact
        logger.info(
            f"Set ingest artifact with index: {artifact.index_name}, "
            f"URL: {artifact.url}"
        )

        # Configure generative model settings using async SDK client
        asyncio.run(self._configure_generative_model_async(artifact))

    def _get_additional_cache_params(self) -> dict[str, Any] | None:
        """
        Include index_name in the cache key to differentiate between different indices.

        Returns:
            Dictionary with index_name if artifact is set, None otherwise
        """
        if self._ingest_artifact is not None:
            return {"index_name": self._ingest_artifact.index_name}
        return None

    async def _configure_generative_model_async(
        self, artifact: OpenRAGIngestArtifact
    ) -> None:
        """Configure the generative model settings using SDK client.

        Args:
            artifact: The ingest artifact containing configuration
        """
        logger.info("Configuring generative model settings")

        # Use SDK client for LLM configuration and index_name
        async with OpenRAGClient(
            base_url=artifact.url, timeout=self.params.timeout
        ) as sdk_client:
            settings_options = SettingsUpdateOptions(
                llm_provider=self.params.generative_model.provider_id,
                llm_model=self.params.generative_model.model_id,
                index_name=artifact.index_name,
            )
            await sdk_client.settings.update(settings_options)

            # Get updated settings to verify
            settings_response = await sdk_client.settings.get()
            logger.info(f"Configured settings via SDK: {settings_response}")

    def process_no_cache(self, benchmark_entry: RagBenchmarkEntry) -> InferenceResult:
        """
        Process a single benchmark entry without using cache.

        Args:
            benchmark_entry: The benchmark entry to process

        Returns:
            InferenceResult with answer, retrieved context, and trajectory
        """
        if self._ingest_artifact is None:
            raise RuntimeError(
                "Ingest artifacts not set. Call set_ingest_artifacts() first."
            )

        question = benchmark_entry.question
        logger.debug(f"Processing question: {question}")

        # Perform inference using async SDK client
        answer, context_ids, trajectory = asyncio.run(
            self._infer_single_async(question)
        )

        # Build inference result
        return InferenceResult(
            answer=answer,
            context_ids=context_ids,
            trajectory=trajectory,
            **benchmark_entry.model_dump(),
        )

    @staticmethod
    async def _stream_chat_response(
        sdk_client: OpenRAGClient, question: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Stream chat response from SDK client and parse events.

        Args:
            sdk_client: The OpenRAG SDK client
            question: The question to ask

        Returns:
            Tuple of (answer, trajectory)
        """
        # Stream the chat response
        answer_parts = []
        trajectory: list[dict[str, Any]] = []

        # Use async context manager to properly initialize the stream
        async with sdk_client.chat.stream(message=question) as stream:
            async for event in stream:
                # Log each event received
                logger.debug(f"Received event: {type(event).__name__} - {event}")

                # Handle different event types from the stream
                if isinstance(event, ContentEvent):
                    # Content event contains the answer text (delta field)
                    answer_parts.append(event.delta)
                elif isinstance(event, SourcesEvent):
                    # Sources event contains retrieved documents
                    # Each SourcesEvent represents a query's results
                    current_sources = [
                        {"filename": source.filename, "text": source.text}
                        for source in event.sources
                    ]
                    # Add this query's results to the list
                    # Use the query field from the SourcesEvent
                    trajectory.append(
                        {
                            "query": event.query,
                            "results": current_sources,
                        }
                    )
                elif isinstance(event, DoneEvent):
                    # Done event signals completion
                    logger.debug("Stream completed")

        answer = "".join(answer_parts)
        return answer, trajectory

    async def _infer_single_async(
        self, question: str
    ) -> tuple[str, list[str], Trajectory | None]:
        """
        Perform inference for a single question using SDK client.

        Args:
            question: The question to answer

        Returns:
            Tuple of (answer, context_ids, trajectory)
        """
        if self._ingest_artifact is None:
            raise RuntimeError(
                "Ingest artifact not set. Call set_ingest_artifacts() first."
            )

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(
                    f"Inference attempt {attempt}/{max_retries} for question: {question}"
                )

                # Use SDK client for chat/inference
                async with OpenRAGClient(
                    base_url=self._ingest_artifact.url, timeout=self.params.timeout
                ) as sdk_client:
                    answer, trajectory = await self._stream_chat_response(
                        sdk_client, question
                    )

                    context_ids = [
                        result["filename"]
                        for query_result in trajectory
                        for result in query_result["results"]
                    ]

                    return answer, context_ids, trajectory

            except Exception as e:
                logger.error(
                    f"Inference attempt {attempt}/{max_retries} failed: {e}\n{traceback.format_exc()}"
                )
                if attempt < max_retries:
                    # Wait before retry (exponential backoff)
                    await asyncio.sleep(2**attempt)

        error_msg = f"Cannot run inference on question '{question}' after {max_retries} attempts. See log for details."
        logger.error(error_msg)
        raise RuntimeError(error_msg)


# Made with Bob
