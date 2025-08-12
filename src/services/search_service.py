from typing import Any, Dict, Optional
from agentd.tool_decorator import tool
from config.settings import clients, INDEX_NAME, EMBED_MODEL
from auth_context import get_auth_context

class SearchService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager
    
    @tool
    async def search_tool(self, query: str) -> Dict[str, Any]:
        """
        Use this tool to search for documents relevant to the query.

        Args:
            query (str): query string to search the corpus  

        Returns:
            dict (str, Any): {"results": [chunks]} on success
        """
        # Get authentication context from the current async context
        user_id, jwt_token = get_auth_context()
        # Embed the query
        resp = await clients.patched_async_client.embeddings.create(model=EMBED_MODEL, input=[query])
        query_embedding = resp.data[0].embedding
        
        # Base query structure
        search_body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "knn": {
                                "chunk_embedding": {
                                    "vector": query_embedding,
                                    "k": 10
                                }
                            }
                        }
                    ]
                }
            },
            "_source": ["filename", "mimetype", "page", "text", "source_url", "owner", "allowed_users", "allowed_groups"],
            "size": 10
        }
        
        # Authentication required - DLS will handle document filtering automatically
        if not user_id:
            return {"results": [], "error": "Authentication required"}
        
        # Get user's OpenSearch client with JWT for OIDC auth  
        opensearch_client = clients.create_user_opensearch_client(jwt_token)
        results = await opensearch_client.search(index=INDEX_NAME, body=search_body)
        
        # Transform results
        chunks = []
        for hit in results["hits"]["hits"]:
            chunks.append({
                "filename": hit["_source"]["filename"],
                "mimetype": hit["_source"]["mimetype"], 
                "page": hit["_source"]["page"],
                "text": hit["_source"]["text"],
                "score": hit["_score"],
                "source_url": hit["_source"].get("source_url"),
                "owner": hit["_source"].get("owner")
            })
        return {"results": chunks}

    async def search(self, query: str, user_id: str = None, jwt_token: str = None) -> Dict[str, Any]:
        """Public search method for API endpoints"""
        # Set auth context if provided (for direct API calls)
        if user_id and jwt_token:
            from auth_context import set_auth_context
            set_auth_context(user_id, jwt_token)
        
        return await self.search_tool(query)