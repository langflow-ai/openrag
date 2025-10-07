"""
Service-level fixtures for testing business logic.
These fixtures provide instances of service classes with necessary dependencies.
"""

import pytest
from pathlib import Path
import sys

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def document_service():
    """Provide a DocumentService instance for testing."""
    from services.document_service import DocumentService

    return DocumentService()


@pytest.fixture
def search_service():
    """Provide a SearchService instance for testing."""
    from services.search_service import SearchService

    return SearchService()


@pytest.fixture
def auth_service():
    """Provide an AuthService instance for testing."""
    from services.auth_service import AuthService

    return AuthService()


@pytest.fixture
def chat_service():
    """Provide a ChatService instance for testing."""
    from services.chat_service import ChatService

    return ChatService()


@pytest.fixture
def knowledge_filter_service():
    """Provide a KnowledgeFilterService instance for testing."""
    from services.knowledge_filter_service import KnowledgeFilterService

    return KnowledgeFilterService()


@pytest.fixture
def flows_service():
    """Provide a FlowsService instance for testing."""
    from services.flows_service import FlowsService

    return FlowsService()


@pytest.fixture
def models_service():
    """Provide a ModelsService instance for testing."""
    from services.models_service import ModelsService

    return ModelsService()


@pytest.fixture
def task_service():
    """Provide a TaskService instance for testing."""
    from services.task_service import TaskService

    return TaskService()


@pytest.fixture
def conversation_persistence_service():
    """Provide a ConversationPersistenceService instance for testing."""
    from services.conversation_persistence_service import ConversationPersistenceService

    return ConversationPersistenceService()


@pytest.fixture
def session_ownership_service():
    """Provide a SessionOwnershipService instance for testing."""
    from services.session_ownership_service import SessionOwnershipService

    return SessionOwnershipService()


@pytest.fixture
def langflow_file_service():
    """Provide a LangflowFileService instance for testing."""
    from services.langflow_file_service import LangflowFileService

    return LangflowFileService()


@pytest.fixture
def langflow_history_service():
    """Provide a LangflowHistoryService instance for testing."""
    from services.langflow_history_service import LangflowHistoryService

    return LangflowHistoryService()


@pytest.fixture
def langflow_mcp_service():
    """Provide a LangflowMCPService instance for testing."""
    from services.langflow_mcp_service import LangflowMCPService

    return LangflowMCPService()


@pytest.fixture
def monitor_service():
    """Provide a MonitorService instance for testing."""
    from services.monitor_service import MonitorService

    return MonitorService()
