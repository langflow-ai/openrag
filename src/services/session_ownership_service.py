"""
Session Ownership Service
Tracks which Google user owns which Langflow session to properly separate message history
"""

import json
import os
from typing import Dict, List, Optional, Set
from datetime import datetime


class SessionOwnershipService:
    """Service to track session ownership for proper message history separation"""
    
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
                print(f"Error loading session ownership data: {e}")
                return {}
        return {}
    
    def _save_ownership_data(self):
        """Save session ownership data to JSON file"""
        try:
            with open(self.ownership_file, 'w') as f:
                json.dump(self.ownership_data, f, indent=2)
            print(f"Saved session ownership data to {self.ownership_file}")
        except Exception as e:
            print(f"Error saving session ownership data: {e}")
    
    def claim_session(self, google_user_id: str, langflow_session_id: str, langflow_user_id: str):
        """Claim a Langflow session for a Google user"""
        if langflow_session_id not in self.ownership_data:
            self.ownership_data[langflow_session_id] = {
                "google_user_id": google_user_id,
                "langflow_user_id": langflow_user_id,
                "created_at": datetime.now().isoformat(),
                "last_accessed": datetime.now().isoformat()
            }
            self._save_ownership_data()
            print(f"Claimed session {langflow_session_id} for Google user {google_user_id}")
        else:
            # Update last accessed time
            self.ownership_data[langflow_session_id]["last_accessed"] = datetime.now().isoformat()
            self._save_ownership_data()
    
    def get_session_owner(self, langflow_session_id: str) -> Optional[str]:
        """Get the Google user ID that owns a Langflow session"""
        session_data = self.ownership_data.get(langflow_session_id)
        return session_data.get("google_user_id") if session_data else None
    
    def get_user_sessions(self, google_user_id: str) -> List[str]:
        """Get all Langflow sessions owned by a Google user"""
        return [
            session_id 
            for session_id, session_data in self.ownership_data.items()
            if session_data.get("google_user_id") == google_user_id
        ]
    
    def get_unowned_sessions_for_langflow_user(self, langflow_user_id: str) -> Set[str]:
        """Get sessions for a Langflow user that aren't claimed by any Google user
        
        This requires querying the Langflow database to get all sessions for the user,
        then filtering out the ones that are already claimed.
        """
        # This will be implemented when we have access to all sessions for a Langflow user
        claimed_sessions = set()
        for session_data in self.ownership_data.values():
            if session_data.get("langflow_user_id") == langflow_user_id:
                claimed_sessions.add(session_data.get("google_user_id"))
        return claimed_sessions
    
    def filter_sessions_for_google_user(self, all_sessions: List[str], google_user_id: str) -> List[str]:
        """Filter a list of sessions to only include those owned by the Google user"""
        user_sessions = self.get_user_sessions(google_user_id)
        return [session for session in all_sessions if session in user_sessions]
    
    def is_session_owned_by_google_user(self, langflow_session_id: str, google_user_id: str) -> bool:
        """Check if a session is owned by a specific Google user"""
        return self.get_session_owner(langflow_session_id) == google_user_id
    
    def get_ownership_stats(self) -> Dict[str, any]:
        """Get statistics about session ownership"""
        google_users = set()
        langflow_users = set()
        
        for session_data in self.ownership_data.values():
            google_users.add(session_data.get("google_user_id"))
            langflow_users.add(session_data.get("langflow_user_id"))
        
        return {
            "total_tracked_sessions": len(self.ownership_data),
            "unique_google_users": len(google_users),
            "unique_langflow_users": len(langflow_users),
            "sessions_per_google_user": {
                google_user: len(self.get_user_sessions(google_user))
                for google_user in google_users
            }
        }


# Global instance
session_ownership_service = SessionOwnershipService()