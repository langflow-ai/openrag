import itertools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Dict, Optional


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DoclingPhaseStatus(Enum):
    """Tracks the state of the Docling conversion sub-phase for a single file."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"


class IngestionPhase(Enum):
    """Tracks which phase of the two-phase ingestion pipeline a file is in.

    DOCLING: file has been submitted to Docling Serve and the backend is
        polling for conversion completion. Langflow has not been called.
    LANGFLOW: Docling conversion succeeded; Langflow ingestion flow is running.
    COMPLETE: Langflow ingestion finished and the document is indexed.
    """

    DOCLING = "docling"
    LANGFLOW = "langflow"
    COMPLETE = "complete"


@dataclass
class FileTask:
    file_path: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    filename: Optional[str] = None  # Original filename for display
    # Two-phase ingestion fields. Only meaningful for processors that submit
    # files to Docling Serve and then trigger Langflow (i.e. LangflowFileProcessor).
    docling_task_id: Optional[str] = None
    docling_status: DoclingPhaseStatus = DoclingPhaseStatus.PENDING
    phase: IngestionPhase = IngestionPhase.DOCLING

    @property
    def duration_seconds(self) -> float:
        """Duration in seconds from creation to last update"""
        return self.updated_at - self.created_at


@dataclass
class UploadTask:
    _id_counter: ClassVar[itertools.count] = itertools.count(1)

    task_id: str
    total_files: int
    processed_files: int = 0
    successful_files: int = 0
    failed_files: int = 0
    file_tasks: Dict[str, FileTask] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    _sequence_number: int = field(init=False, repr=False)

    def __post_init__(self):
        self._sequence_number = next(UploadTask._id_counter)

    @property
    def sequence_number(self) -> int:
        return self._sequence_number

    @property
    def duration_seconds(self) -> float:
        """Duration in seconds from creation to last update"""
        return self.updated_at - self.created_at
