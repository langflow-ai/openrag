from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DocumentACL:
    """Access Control List information for a document"""
    owner: str = None
    user_permissions: Dict[str, str] = None  # user email -> permission level (read, write, owner)
    group_permissions: Dict[str, str] = None  # group identifier -> permission level
    
    def __post_init__(self):
        if self.user_permissions is None:
            self.user_permissions = {}
        if self.group_permissions is None:
            self.group_permissions = {}
    
    @property
    def allowed_users(self) -> List[str]:
        """Get list of users with any access"""
        return list(self.user_permissions.keys())
    
    @property
    def allowed_groups(self) -> List[str]:
        """Get list of groups with any access"""
        return list(self.group_permissions.keys())


@dataclass 
class ConnectorDocument:
    """Document from a connector with metadata"""
    id: str
    filename: str
    mimetype: str
    content: bytes
    source_url: str
    acl: DocumentACL
    modified_time: datetime
    created_time: datetime
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseConnector(ABC):
    """Base class for all document connectors"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._authenticated = False
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the service"""
        pass
    
    @abstractmethod
    async def setup_subscription(self) -> str:
        """Set up real-time subscription for file changes. Returns subscription ID."""
        pass
    
    @abstractmethod
    async def list_files(self, page_token: Optional[str] = None) -> Dict[str, Any]:
        """List all files. Returns files and next_page_token if any."""
        pass
    
    @abstractmethod
    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Get file content and metadata"""
        pass
    
    @abstractmethod
    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        """Handle webhook notification. Returns list of affected file IDs."""
        pass
    
    @abstractmethod
    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """Clean up subscription"""
        pass
    
    @property
    def is_authenticated(self) -> bool:
        return self._authenticated