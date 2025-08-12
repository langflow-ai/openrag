from config.settings import clients, LANGFLOW_URL, FLOW_ID, LANGFLOW_KEY
from agent import async_chat, async_langflow, async_chat_stream, async_langflow_stream
from auth_context import set_auth_context

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

    async def langflow_chat(self, prompt: str, previous_response_id: str = None, stream: bool = False):
        """Handle Langflow chat requests"""
        if not prompt:
            raise ValueError("Prompt is required")

        if not LANGFLOW_URL or not FLOW_ID or not LANGFLOW_KEY:
            raise ValueError("LANGFLOW_URL, FLOW_ID, and LANGFLOW_KEY environment variables are required")

        if stream:
            return async_langflow_stream(clients.langflow_client, FLOW_ID, prompt, previous_response_id=previous_response_id)
        else:
            response_text, response_id = await async_langflow(clients.langflow_client, FLOW_ID, prompt, previous_response_id=previous_response_id)
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            return response_data

    async def upload_context_chat(self, document_content: str, filename: str, 
                                 previous_response_id: str = None, endpoint: str = "langflow"):
        """Send document content as user message to get proper response_id"""
        document_prompt = f"I'm uploading a document called '{filename}'. Here is its content:\n\n{document_content}\n\nPlease confirm you've received this document and are ready to answer questions about it."
        
        if endpoint == "langflow":
            response_text, response_id = await async_langflow(clients.langflow_client, FLOW_ID, document_prompt, previous_response_id=previous_response_id)
        else:  # chat
            response_text, response_id = await async_chat(clients.patched_async_client, document_prompt, previous_response_id=previous_response_id)
        
        return response_text, response_id