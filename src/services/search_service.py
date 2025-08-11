from typing import Any, Dict, Optional
from agentd.tool_decorator import tool
from config.settings import clients, INDEX_NAME, EMBED_MODEL

class SearchService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager
    
    @tool  # TODO: This will be broken until we figure out how to pass JWT through @tool decorator
    async def search_tool(self, query: str, user_id: str = None, jwt_token: str = None) -> Dict[str, Any]:
        """
        Use this tool to search for documents relevant to the query.

        Args:
            query (str): query string to search the corpus  
            user_id (str): user ID for access control (optional)

        Returns:
            dict (str, Any): {"results": [chunks]} on success
        """
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
        opensearch_client = self.session_manager.get_user_opensearch_client(user_id, jwt_token)
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
        return await self.search_tool(query, user_id, jwt_token)