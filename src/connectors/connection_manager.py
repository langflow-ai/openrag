import json
import uuid
import asyncio
import aiofiles
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path

from .base import BaseConnector
from .google_drive import GoogleDriveConnector


@dataclass
class ConnectionConfig:
    """Configuration for a connector connection"""
    connection_id: str
    connector_type: str  # "google_drive", "box", etc.
    name: str  # User-friendly name
    config: Dict[str, Any]  # Connector-specific config
    user_id: Optional[str] = None  # For multi-tenant support
    created_at: datetime = None
    last_sync: Optional[datetime] = None
    is_active: bool = True
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class ConnectionManager:
    """Manages multiple connector connections with persistence"""
    
    def __init__(self, connections_file: str = "connections.json"):
        self.connections_file = Path(connections_file)
        self.connections: Dict[str, ConnectionConfig] = {}
        self.active_connectors: Dict[str, BaseConnector] = {}
        
    async def load_connections(self):
        """Load connections from persistent storage"""
        if self.connections_file.exists():
            async with aiofiles.open(self.connections_file, 'r') as f:
                data = json.loads(await f.read())
                
            for conn_data in data.get('connections', []):
                # Convert datetime strings back to datetime objects
                if conn_data.get('created_at'):
                    conn_data['created_at'] = datetime.fromisoformat(conn_data['created_at'])
                if conn_data.get('last_sync'):
                    conn_data['last_sync'] = datetime.fromisoformat(conn_data['last_sync'])
                    
                config = ConnectionConfig(**conn_data)
                self.connections[config.connection_id] = config
    
    async def save_connections(self):
        """Save connections to persistent storage"""
        data = {
            'connections': []
        }
        
        for config in self.connections.values():
            conn_data = asdict(config)
            # Convert datetime objects to strings
            if conn_data.get('created_at'):
                conn_data['created_at'] = conn_data['created_at'].isoformat()
            if conn_data.get('last_sync'):
                conn_data['last_sync'] = conn_data['last_sync'].isoformat()
            data['connections'].append(conn_data)
        
        async with aiofiles.open(self.connections_file, 'w') as f:
            await f.write(json.dumps(data, indent=2))
    
    async def create_connection(self, connector_type: str, name: str, config: Dict[str, Any], user_id: Optional[str] = None) -> str:
        """Create a new connection configuration"""
        connection_id = str(uuid.uuid4())
        
        connection_config = ConnectionConfig(
            connection_id=connection_id,
            connector_type=connector_type,
            name=name,
            config=config,
            user_id=user_id
        )
        
        self.connections[connection_id] = connection_config
        await self.save_connections()
        
        return connection_id
    
    async def get_connection(self, connection_id: str) -> Optional[ConnectionConfig]:
        """Get connection configuration"""
        return self.connections.get(connection_id)
    
    async def update_connection(self, connection_id: str, connector_type: str = None, name: str = None, 
                              config: Dict[str, Any] = None, user_id: str = None) -> bool:
        """Update an existing connection configuration"""
        if connection_id not in self.connections:
            return False
        
        connection = self.connections[connection_id]
        
        # Update fields if provided
        if connector_type is not None:
            connection.connector_type = connector_type
        if name is not None:
            connection.name = name
        if config is not None:
            connection.config = config
        if user_id is not None:
            connection.user_id = user_id
        
        await self.save_connections()
        return True
    
    async def list_connections(self, user_id: Optional[str] = None, connector_type: Optional[str] = None) -> List[ConnectionConfig]:
        """List connections, optionally filtered by user or connector type"""
        connections = list(self.connections.values())
        
        if user_id is not None:
            connections = [c for c in connections if c.user_id == user_id]
        
        if connector_type is not None:
            connections = [c for c in connections if c.connector_type == connector_type]
        
        return connections
    
    async def delete_connection(self, connection_id: str) -> bool:
        """Delete a connection"""
        if connection_id not in self.connections:
            return False
        
        # Clean up active connector if exists
        if connection_id in self.active_connectors:
            connector = self.active_connectors[connection_id]
            # Try to cleanup subscriptions if applicable
            try:
                if hasattr(connector, 'webhook_channel_id') and connector.webhook_channel_id:
                    await connector.cleanup_subscription(connector.webhook_channel_id)
            except:
                pass  # Best effort cleanup
            
            del self.active_connectors[connection_id]
        
        del self.connections[connection_id]
        await self.save_connections()
        return True
    
    async def get_connector(self, connection_id: str) -> Optional[BaseConnector]:
        """Get an active connector instance"""
        # Return cached connector if available
        if connection_id in self.active_connectors:
            connector = self.active_connectors[connection_id]
            if connector.is_authenticated:
                return connector
            else:
                # Remove unauthenticated connector from cache
                del self.active_connectors[connection_id]
        
        # Try to create and authenticate connector
        connection_config = self.connections.get(connection_id)
        if not connection_config or not connection_config.is_active:
            return None
        
        connector = self._create_connector(connection_config)
        if await connector.authenticate():
            self.active_connectors[connection_id] = connector
            return connector
        
        return None
    
    def _create_connector(self, config: ConnectionConfig) -> BaseConnector:
        """Factory method to create connector instances"""
        if config.connector_type == "google_drive":
            return GoogleDriveConnector(config.config)
        elif config.connector_type == "box":
            # Future: BoxConnector(config.config)
            raise NotImplementedError("Box connector not implemented yet")
        elif config.connector_type == "dropbox":
            # Future: DropboxConnector(config.config)
            raise NotImplementedError("Dropbox connector not implemented yet")
        else:
            raise ValueError(f"Unknown connector type: {config.connector_type}")
    
    async def update_last_sync(self, connection_id: str):
        """Update the last sync timestamp for a connection"""
        if connection_id in self.connections:
            self.connections[connection_id].last_sync = datetime.now()
            await self.save_connections()
    
    async def activate_connection(self, connection_id: str) -> bool:
        """Activate a connection"""
        if connection_id in self.connections:
            self.connections[connection_id].is_active = True
            await self.save_connections()
            return True
        return False
    
    async def deactivate_connection(self, connection_id: str) -> bool:
        """Deactivate a connection"""
        if connection_id in self.connections:
            self.connections[connection_id].is_active = False
            await self.save_connections()
            
            # Remove from active connectors
            if connection_id in self.active_connectors:
                del self.active_connectors[connection_id]
            
            return True
        return False