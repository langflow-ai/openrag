from config.settings import NUDGES_FLOW_ID, LANGFLOW_URL, LANGFLOW_CHAT_FLOW_ID, LANGFLOW_INGEST_FLOW_ID
import json
import os
import aiohttp
from utils.logging_config import get_logger

logger = get_logger(__name__)


class FlowsService:

    async def reset_langflow_flow(self, flow_type: str):
        """Reset a Langflow flow by uploading the corresponding JSON file
        
        Args:
            flow_type: Either 'nudges', 'retrieval', or 'ingest'
            
        Returns:
            dict: Success/error response
        """
        if not LANGFLOW_URL:
            raise ValueError("LANGFLOW_URL environment variable is required")
        
        # Determine flow file and ID based on type
        if flow_type == "nudges":
            flow_file = "flows/openrag_nudges.json"
            flow_id = NUDGES_FLOW_ID
        elif flow_type == "retrieval":
            flow_file = "flows/openrag_agent.json" 
            flow_id = LANGFLOW_CHAT_FLOW_ID
        elif flow_type == "ingest":
            flow_file = "flows/ingestion_flow.json"
            flow_id = LANGFLOW_INGEST_FLOW_ID
        else:
            raise ValueError("flow_type must be either 'nudges', 'retrieval', or 'ingest'")
            
        # Load flow JSON file
        try:
            # Get the project root directory (go up from src/services/ to project root)
            # __file__ is src/services/chat_service.py
            # os.path.dirname(__file__) is src/services/
            # os.path.dirname(os.path.dirname(__file__)) is src/
            # os.path.dirname(os.path.dirname(os.path.dirname(__file__))) is project root
            current_file_dir = os.path.dirname(os.path.abspath(__file__))  # src/services/
            src_dir = os.path.dirname(current_file_dir)  # src/
            project_root = os.path.dirname(src_dir)  # project root
            flow_path = os.path.join(project_root, flow_file)
            
            if not os.path.exists(flow_path):
                # List contents of project root to help debug
                try:
                    contents = os.listdir(project_root)
                    logger.info(f"Project root contents: {contents}")
                    
                    flows_dir = os.path.join(project_root, "flows")
                    if os.path.exists(flows_dir):
                        flows_contents = os.listdir(flows_dir)
                        logger.info(f"Flows directory contents: {flows_contents}")
                    else:
                        logger.info("Flows directory does not exist")
                except Exception as e:
                    logger.error(f"Error listing directory contents: {e}")
                    
                raise FileNotFoundError(f"Flow file not found at: {flow_path}")
                
            with open(flow_path, 'r') as f:
                flow_data = json.load(f)
            logger.info(f"Successfully loaded flow data from {flow_file}")
        except FileNotFoundError:
            raise ValueError(f"Flow file not found: {flow_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in flow file {flow_file}: {e}")
            
        # Get API key for Langflow
        from config.settings import LANGFLOW_KEY
        if not LANGFLOW_KEY:
            raise ValueError("LANGFLOW_KEY is required for flow reset")
            
        # Make PATCH request to Langflow API to update the flow
        url = f"{LANGFLOW_URL}/api/v1/flows/{flow_id}"
        headers = {
            "x-api-key": LANGFLOW_KEY,
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=flow_data, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(
                            f"Successfully reset {flow_type} flow",
                            flow_id=flow_id,
                            flow_file=flow_file
                        )
                        return {
                            "success": True,
                            "message": f"Successfully reset {flow_type} flow",
                            "flow_id": flow_id,
                            "flow_type": flow_type
                        }
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Failed to reset {flow_type} flow",
                            status_code=response.status,
                            error=error_text
                        )
                        return {
                            "success": False,
                            "error": f"Failed to reset flow: HTTP {response.status} - {error_text}"
                        }
        except aiohttp.ClientError as e:
            logger.error(f"Network error while resetting {flow_type} flow", error=str(e))
            return {
                "success": False,
                "error": f"Network error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Unexpected error while resetting {flow_type} flow", error=str(e))
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }
