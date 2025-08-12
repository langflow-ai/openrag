from config.settings import clients, LANGFLOW_URL, FLOW_ID, LANGFLOW_KEY
from agent import async_chat, async_langflow, async_chat_stream, async_langflow_stream
from auth_context import set_auth_context
import json

class ChatService:
    
    async def chat(self, prompt: str, user_id: str = None, jwt_token: str = None, previous_response_id: str = None, stream: bool = False):
        """Handle chat requests using the patched OpenAI client"""
        if not prompt:
            raise ValueError("Prompt is required")
        
        # Set authentication context for this request so tools can access it
        if user_id and jwt_token:
            set_auth_context(user_id, jwt_token)
        
        if stream:
            return async_chat_stream(clients.patched_async_client, prompt, user_id, previous_response_id=previous_response_id)
        else:
            response_text, response_id = await async_chat(clients.patched_async_client, prompt, user_id, previous_response_id=previous_response_id)
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            return response_data

    async def langflow_chat(self, prompt: str, jwt_token: str = None, previous_response_id: str = None, stream: bool = False):
        """Handle Langflow chat requests"""
        if not prompt:
            raise ValueError("Prompt is required")

        if not LANGFLOW_URL or not FLOW_ID or not LANGFLOW_KEY:
            raise ValueError("LANGFLOW_URL, FLOW_ID, and LANGFLOW_KEY environment variables are required")

        # Prepare extra headers for JWT authentication
        extra_headers = {}
        if jwt_token:
            extra_headers['X-LANGFLOW-GLOBAL-VAR-JWT'] = jwt_token

        # Get context variables for filters, limit, and threshold
        from auth_context import get_search_filters, get_search_limit, get_score_threshold
        filters = get_search_filters()
        limit = get_search_limit()
        score_threshold = get_score_threshold()

        # Build the complete filter expression like the search service does
        filter_expression = {}
        if filters:
            filter_clauses = []
            # Map frontend filter names to backend field names
            field_mapping = {
                "data_sources": "filename",
                "document_types": "mimetype", 
                "owners": "owner"
            }
            
            for filter_key, values in filters.items():
                if values is not None and isinstance(values, list) and len(values) > 0:
                    # Map frontend key to backend field name
                    field_name = field_mapping.get(filter_key, filter_key)
                    
                    if len(values) == 1:
                        # Single value filter
                        filter_clauses.append({"term": {field_name: values[0]}})
                    else:
                        # Multiple values filter
                        filter_clauses.append({"terms": {field_name: values}})
            
            if filter_clauses:
                filter_expression["filter"] = filter_clauses
        
        # Add limit and score threshold to the filter expression (only if different from defaults)
        if limit and limit != 10:  # 10 is the default limit
            filter_expression["limit"] = limit
            
        if score_threshold and score_threshold != 0:  # 0 is the default threshold
            filter_expression["score_threshold"] = score_threshold

        # Pass the complete filter expression as a single header to Langflow (only if we have something to send)
        if filter_expression:
            print(f"Sending GenDB query filter to Langflow: {json.dumps(filter_expression, indent=2)}")
            extra_headers['X-LANGFLOW-GLOBAL-VAR-GENDB-QUERY-FILTER'] = json.dumps(filter_expression)

        if stream:
            return async_langflow_stream(clients.langflow_client, FLOW_ID, prompt, extra_headers=extra_headers, previous_response_id=previous_response_id)
        else:
            response_text, response_id = await async_langflow(clients.langflow_client, FLOW_ID, prompt, extra_headers=extra_headers, previous_response_id=previous_response_id)
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            return response_data

    async def upload_context_chat(self, document_content: str, filename: str, 
                                 user_id: str = None, jwt_token: str = None, previous_response_id: str = None, endpoint: str = "langflow"):
        """Send document content as user message to get proper response_id"""
        document_prompt = f"I'm uploading a document called '{filename}'. Here is its content:\n\n{document_content}\n\nPlease confirm you've received this document and are ready to answer questions about it."
        
        if endpoint == "langflow":
            # Prepare extra headers for JWT authentication
            extra_headers = {}
            if jwt_token:
                extra_headers['X-LANGFLOW-GLOBAL-VAR-JWT'] = jwt_token
            response_text, response_id = await async_langflow(clients.langflow_client, FLOW_ID, document_prompt, extra_headers=extra_headers, previous_response_id=previous_response_id)
        else:  # chat
            # Set auth context for chat tools and provide user_id
            if user_id and jwt_token:
                set_auth_context(user_id, jwt_token)
            response_text, response_id = await async_chat(clients.patched_async_client, document_prompt, user_id, previous_response_id=previous_response_id)
        
        return response_text, response_id