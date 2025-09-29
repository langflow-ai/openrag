"""
Conversation Persistence Service
Simple service to persist chat conversations to disk so they survive server restarts
"""

import json
import os
from typing import Dict, Any
from datetime import datetime
import threading
from utils.logging_config import get_logger

logger = get_logger(__name__)

class ConversationPersistenceService:
    """Simple service to persist conversations to disk"""
    
    def __init__(self, storage_file: str = "conversations.json"):
        self.storage_file = storage_file
        self.lock = threading.Lock()
        self._conversations = self._load_conversations()
    
    def _load_conversations(self) -> Dict[str, Dict[str, Any]]:
        """Load conversations from disk"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.debug(f"Loaded {self._count_total_conversations(data)} conversations from {self.storage_file}")
                    return data
            except Exception as e:
                logger.error(f"Error loading conversations from {self.storage_file}: {e}")
                return {}
        return {}
    
    def _save_conversations(self):
        """Save conversations to disk"""
        try:
            with self.lock:
                with open(self.storage_file, 'w', encoding='utf-8') as f:
                    json.dump(self._conversations, f, indent=2, ensure_ascii=False, default=str)
                logger.debug(f"Saved {self._count_total_conversations(self._conversations)} conversations to {self.storage_file}")
        except Exception as e:
            logger.error(f"Error saving conversations to {self.storage_file}: {e}")
    
    def _count_total_conversations(self, data: Dict[str, Any]) -> int:
        """Count total conversations across all users"""
        total = 0
        for user_conversations in data.values():
            if isinstance(user_conversations, dict):
                total += len(user_conversations)
        return total
    
    def get_user_conversations(self, user_id: str) -> Dict[str, Any]:
        """Get all conversations for a user"""
        if user_id not in self._conversations:
            self._conversations[user_id] = {}
        return self._conversations[user_id]
    
    def _serialize_datetime(self, obj: Any) -> Any:
        """Recursively convert datetime objects to ISO strings for JSON serialization"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {key: self._serialize_datetime(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_datetime(item) for item in obj]
        else:
            return obj
    
    def store_conversation_thread(self, user_id: str, response_id: str, conversation_state: Dict[str, Any]):
        """Store a conversation thread and persist to disk"""
        if user_id not in self._conversations:
            self._conversations[user_id] = {}
        
        # Recursively convert datetime objects to strings for JSON serialization
        serialized_conversation = self._serialize_datetime(conversation_state)
        
        self._conversations[user_id][response_id] = serialized_conversation
        
        # Save to disk (we could optimize this with batching if needed)
        self._save_conversations()
    
    def get_conversation_thread(self, user_id: str, response_id: str) -> Dict[str, Any]:
        """Get a specific conversation thread"""
        user_conversations = self.get_user_conversations(user_id)
        return user_conversations.get(response_id, {})
    
    def delete_conversation_thread(self, user_id: str, response_id: str) -> bool:
        """Delete a specific conversation thread"""
        if user_id in self._conversations and response_id in self._conversations[user_id]:
            del self._conversations[user_id][response_id]
            self._save_conversations()
            logger.debug(f"Deleted conversation {response_id} for user {user_id}")
            return True
        return False
    
    def clear_user_conversations(self, user_id: str):
        """Clear all conversations for a user"""
        if user_id in self._conversations:
            del self._conversations[user_id]
            self._save_conversations()
            logger.debug(f"Cleared all conversations for user {user_id}")
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get statistics about stored conversations"""
        total_users = len(self._conversations)
        total_conversations = self._count_total_conversations(self._conversations)
        
        user_stats = {}
        for user_id, conversations in self._conversations.items():
            user_stats[user_id] = {
                'conversation_count': len(conversations),
                'latest_activity': max(
                    (conv.get('last_activity', '') for conv in conversations.values()),
                    default=''
                )
            }
        
        return {
            'total_users': total_users,
            'total_conversations': total_conversations,
            'storage_file': self.storage_file,
            'file_exists': os.path.exists(self.storage_file),
            'user_stats': user_stats
        }


# Global instance
conversation_persistence = ConversationPersistenceService()