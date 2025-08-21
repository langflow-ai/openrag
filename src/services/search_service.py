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
        # Get search filters, limit, and score threshold from context
        from auth_context import get_search_filters, get_search_limit, get_score_threshold
        filters = get_search_filters() or {}
        limit = get_search_limit()
        score_threshold = get_score_threshold()
        # Detect wildcard request ("*") to return global facets/stats without semantic search
        is_wildcard_match_all = isinstance(query, str) and query.strip() == "*"

        # Only embed when not doing match_all
        if not is_wildcard_match_all:
            resp = await clients.patched_async_client.embeddings.create(model=EMBED_MODEL, input=[query])
            query_embedding = resp.data[0].embedding
        
        # Build filter clauses
        filter_clauses = []
        if filters:
            # Map frontend filter names to backend field names
            field_mapping = {
                "data_sources": "filename",
                "document_types": "mimetype", 
                "owners": "owner_name.keyword",
                "connector_types": "connector_type"
            }
            
            for filter_key, values in filters.items():
                if values is not None and isinstance(values, list):
                    # Map frontend key to backend field name
                    field_name = field_mapping.get(filter_key, filter_key)
                    
                    if len(values) == 0:
                        # Empty array means "match nothing" - use impossible filter
                        filter_clauses.append({"term": {field_name: "__IMPOSSIBLE_VALUE__"}})
                    elif len(values) == 1:
                        # Single value filter
                        filter_clauses.append({"term": {field_name: values[0]}})
                    else:
                        # Multiple values filter
                        filter_clauses.append({"terms": {field_name: values}})
        
        # Build query body
        if is_wildcard_match_all:
            # Match all documents; still allow filters to narrow scope
            if filter_clauses:
                query_block = {"bool": {"filter": filter_clauses}}
            else:
                query_block = {"match_all": {}}
        else:
            # Hybrid search query structure (semantic + keyword)
            query_block = {
                "bool": {
                    "should": [
                        {
                            "knn": {
                                "chunk_embedding": {
                                    "vector": query_embedding,
                                    "k": 10,
                                    "boost": 0.7
                                }
                            }
                        },
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["text^2", "filename^1.5"],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                                "boost": 0.3
                            }
                        }
                    ],
                    "minimum_should_match": 1,
                    **({"filter": filter_clauses} if filter_clauses else {})
                }
            }

        search_body = {
            "query": query_block,
            "aggs": {
                "data_sources": {
                    "terms": {
                        "field": "filename",
                        "size": 20
                    }
                },
                "document_types": {
                    "terms": {
                        "field": "mimetype",
                        "size": 10
                    }
                },
                "owners": {
                    "terms": {
                        "field": "owner_name.keyword",
                        "size": 10
                    }
                },
                "connector_types": {
                    "terms": {
                        "field": "connector_type",
                        "size": 10
                    }
                }
            },
            "_source": ["filename", "mimetype", "page", "text", "source_url", "owner", "owner_name", "owner_email", "file_size", "connector_type", "allowed_users", "allowed_groups"],
            "size": limit
        }
        
        # Add score threshold only for hybrid (not meaningful for match_all)
        if not is_wildcard_match_all and score_threshold > 0:
            search_body["min_score"] = score_threshold
        
        # Authentication required - DLS will handle document filtering automatically
        if not user_id:
            return {"results": [], "error": "Authentication required"}
        
        # Get user's OpenSearch client with JWT for OIDC auth  
        opensearch_client = clients.create_user_opensearch_client(jwt_token)
        
        try:
            results = await opensearch_client.search(index=INDEX_NAME, body=search_body)
        except Exception as e:
            print(f"[ERROR] OpenSearch query failed: {e}")
            print(f"[ERROR] Search body: {search_body}")
            # Re-raise the exception so the API returns the error to frontend
            raise
        
        # Transform results (keep for backward compatibility)
        chunks = []
        for hit in results["hits"]["hits"]:
            chunks.append({
                "filename": hit["_source"]["filename"],
                "mimetype": hit["_source"]["mimetype"], 
                "page": hit["_source"]["page"],
                "text": hit["_source"]["text"],
                "score": hit["_score"],
                "source_url": hit["_source"].get("source_url"),
                "owner": hit["_source"].get("owner"),
                "owner_name": hit["_source"].get("owner_name"),
                "owner_email": hit["_source"].get("owner_email"),
                "file_size": hit["_source"].get("file_size"),
                "connector_type": hit["_source"].get("connector_type")
            })
        
        # Return both transformed results and aggregations
        return {
            "results": chunks,
            "aggregations": results.get("aggregations", {}),
            "total": (results.get("hits", {}).get("total", {}).get("value") if isinstance(results.get("hits", {}).get("total"), dict) else results.get("hits", {}).get("total"))
        }

    async def search(self, query: str, user_id: str = None, jwt_token: str = None, filters: Dict[str, Any] = None, limit: int = 10, score_threshold: float = 0) -> Dict[str, Any]:
        """Public search method for API endpoints"""
        # Set auth context if provided (for direct API calls)
        if user_id and jwt_token:
            from auth_context import set_auth_context
            set_auth_context(user_id, jwt_token)
        
        # Set filters and limit in context if provided
        if filters:
            from auth_context import set_search_filters
            set_search_filters(filters)
        
        from auth_context import set_search_limit, set_score_threshold
        set_search_limit(limit)
        set_score_threshold(score_threshold)
        
        return await self.search_tool(query)