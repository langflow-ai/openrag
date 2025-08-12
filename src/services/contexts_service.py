from typing import Any, Dict, Optional

CONTEXTS_INDEX_NAME = "search_contexts"

class ContextsService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager
    
    async def create_context(self, context_doc: Dict[str, Any], user_id: str = None, jwt_token: str = None) -> Dict[str, Any]:
        """Create a new search context"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)
            
            # Index the context document
            result = await opensearch_client.index(
                index=CONTEXTS_INDEX_NAME,
                id=context_doc["id"],
                body=context_doc
            )
            
            if result.get("result") == "created":
                return {"success": True, "id": context_doc["id"], "context": context_doc}
            else:
                return {"success": False, "error": "Failed to create context"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def search_contexts(self, query: str, user_id: str = None, jwt_token: str = None, limit: int = 20) -> Dict[str, Any]:
        """Search for contexts by name, description, or query content"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth  
            opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)
            
            if query.strip():
                # Search across name, description, and query_data fields
                search_body = {
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["name^3", "description^2", "query_data"],
                            "type": "best_fields",
                            "fuzziness": "AUTO"
                        }
                    },
                    "sort": [
                        {"_score": {"order": "desc"}},
                        {"updated_at": {"order": "desc"}}
                    ],
                    "_source": ["id", "name", "description", "query_data", "owner", "created_at", "updated_at"],
                    "size": limit
                }
            else:
                # No query - return all contexts sorted by most recent
                search_body = {
                    "query": {"match_all": {}},
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "_source": ["id", "name", "description", "query_data", "owner", "created_at", "updated_at"],
                    "size": limit
                }
            
            result = await opensearch_client.search(index=CONTEXTS_INDEX_NAME, body=search_body)
            
            # Transform results
            contexts = []
            for hit in result["hits"]["hits"]:
                context = hit["_source"]
                context["score"] = hit.get("_score")
                contexts.append(context)
            
            return {"success": True, "contexts": contexts}
            
        except Exception as e:
            return {"success": False, "error": str(e), "contexts": []}
    
    async def get_context(self, context_id: str, user_id: str = None, jwt_token: str = None) -> Dict[str, Any]:
        """Get a specific context by ID"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)
            
            result = await opensearch_client.get(index=CONTEXTS_INDEX_NAME, id=context_id)
            
            if result.get("found"):
                context = result["_source"]
                return {"success": True, "context": context}
            else:
                return {"success": False, "error": "Context not found"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def update_context(self, context_id: str, updates: Dict[str, Any], user_id: str = None, jwt_token: str = None) -> Dict[str, Any]:
        """Update an existing context"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)
            
            # Update the document
            result = await opensearch_client.update(
                index=CONTEXTS_INDEX_NAME,
                id=context_id,
                body={"doc": updates}
            )
            
            if result.get("result") in ["updated", "noop"]:
                # Get the updated document
                updated_doc = await opensearch_client.get(index=CONTEXTS_INDEX_NAME, id=context_id)
                return {"success": True, "context": updated_doc["_source"]}
            else:
                return {"success": False, "error": "Failed to update context"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def delete_context(self, context_id: str, user_id: str = None, jwt_token: str = None) -> Dict[str, Any]:
        """Delete a context"""
        try:
            # Get user's OpenSearch client with JWT for OIDC auth
            opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)
            
            result = await opensearch_client.delete(index=CONTEXTS_INDEX_NAME, id=context_id)
            
            if result.get("result") == "deleted":
                return {"success": True, "message": "Context deleted successfully"}
            else:
                return {"success": False, "error": "Failed to delete context"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}