"""
Session Ownership Service
Simple service that tracks which user owns which session
"""

import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from utils.logging_config import get_logger

logger = get_logger(__name__)

class SessionOwnershipService:
    """Simple service to track which user owns which session"""
    
    def __init__(self):
        self.ownership_file = "session_ownership.json"
        self.ownership_data = self._load_ownership_data()
    
    def _load_ownership_data(self) -> Dict[str, Dict[str, any]]:
        """Load session ownership data from JSON file"""
        if os.path.exists(self.ownership_file):
            try:
                with open(self.ownership_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading session ownership data: {e}")
                return {}
        return {}
    
    def _save_ownership_data(self):
        """Save session ownership data to JSON file"""
        try:
            with open(self.ownership_file, 'w') as f:
                json.dump(self.ownership_data, f, indent=2)
            logger.debug(f"Saved session ownership data to {self.ownership_file}")
        except Exception as e:
            logger.error(f"Error saving session ownership data: {e}")
    
    def claim_session(self, user_id: str, session_id: str):
        """Claim a session for a user"""
        if session_id not in self.ownership_data:
            self.ownership_data[session_id] = {
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "last_accessed": datetime.now().isoformat()
            }
            self._save_ownership_data()
            logger.debug(f"Claimed session {session_id} for user {user_id}")
        else:
            # Update last accessed time
            self.ownership_data[session_id]["last_accessed"] = datetime.now().isoformat()
            self._save_ownership_data()
    
    def get_session_owner(self, session_id: str) -> Optional[str]:
        """Get the user ID that owns a session"""
        session_data = self.ownership_data.get(session_id)
        return session_data.get("user_id") if session_data else None
    
    def get_user_sessions(self, user_id: str) -> List[str]:
        """Get all sessions owned by a user"""
        return [
            session_id 
            for session_id, session_data in self.ownership_data.items()
            if session_data.get("user_id") == user_id
        ]
    
    def is_session_owned_by_user(self, session_id: str, user_id: str) -> bool:
        """Check if a session is owned by a specific user"""
        return self.get_session_owner(session_id) == user_id
    
    def filter_sessions_for_user(self, session_ids: List[str], user_id: str) -> List[str]:
        """Filter a list of sessions to only include those owned by the user"""
        user_sessions = self.get_user_sessions(user_id)
        return [session for session in session_ids if session in user_sessions]

    def release_session(self, user_id: str, session_id: str) -> bool:
        """Release a session from a user (delete ownership record)"""
        if session_id in self.ownership_data:
            # Verify the user owns this session before deleting
            if self.ownership_data[session_id].get("user_id") == user_id:
                del self.ownership_data[session_id]
                self._save_ownership_data()
                logger.debug(f"Released session {session_id} from user {user_id}")
                return True
            else:
                logger.warning(f"User {user_id} tried to release session {session_id} they don't own")
                return False
        return False
    
    def get_ownership_stats(self) -> Dict[str, any]:
        """Get statistics about session ownership"""
        users = set()
        for session_data in self.ownership_data.values():
            users.add(session_data.get("user_id"))
        
        return {
            "total_tracked_sessions": len(self.ownership_data),
            "unique_users": len(users),
            "sessions_per_user": {
                user: len(self.get_user_sessions(user))
                for user in users if user
            }
        }


# Global instance
session_ownership_service = SessionOwnershipService()