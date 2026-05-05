import time
from typing import Any, Dict, Optional

from utils.logging_config import get_logger
from .processors import TaskProcessor
from .tasks import UploadTask, FileTask, TaskStatus

logger = get_logger(__name__)


class LangflowUrlProcessor(TaskProcessor):
    """Processor for Langflow URL ingestion flow as a tracked task."""

    def __init__(
        self,
        langflow_file_service,
        session_manager,
        docs_url: str,
        crawl_depth: int,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        connector_type: str = "openrag_docs",
        prevent_outside: bool = True,
        tweaks: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        self.langflow_file_service = langflow_file_service
        self.session_manager = session_manager
        self.docs_url = docs_url
        self.crawl_depth = crawl_depth
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.connector_type = connector_type
        self.prevent_outside = prevent_outside
        self.tweaks = tweaks

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process one URL ingestion item through Langflow."""
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            effective_jwt = self.jwt_token
            if self.session_manager and not effective_jwt:
                effective_jwt = self.session_manager.get_effective_jwt_token(
                    self.owner_user_id, self.jwt_token
                )

            result = await self.langflow_file_service.run_url_ingestion_flow(
                docs_url=self.docs_url,
                crawl_depth=self.crawl_depth,
                jwt_token=effective_jwt,
                owner=self.owner_user_id,
                owner_name=self.owner_name,
                owner_email=self.owner_email,
                connector_type=self.connector_type,
                prevent_outside=self.prevent_outside,
                tweaks=self.tweaks,
            )
            # docs_after = await self._count_system_default_docs(opensearch_client)
            # logger.info(
            #     "URL ingestion after",
            #     docs_after=docs_after,
            # )
            # # OpenSearch visibility can lag indexing by a refresh interval.
            # # Retry a few times before declaring ingestion failed.
            # for _ in range(5):
            #     if docs_after > 0:
            #         break
            #     await asyncio.sleep(1)
            #     docs_after = await self._count_system_default_docs(opensearch_client)
            # if docs_after <= 0:
            #     raise ValueError(
            #         "URL ingestion completed but no OpenRAG docs were indexed"
            #     )
            # logger.info(
            #     "URL ingestion indexed OpenRAG docs",
            #     docs_before=docs_before,
            #     docs_after=docs_after,
            # )

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
