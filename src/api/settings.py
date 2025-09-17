from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import (
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    LANGFLOW_PUBLIC_URL,
    clients,
    get_openrag_config,
    config_manager,
)

logger = get_logger(__name__)



async def get_settings(request, session_manager):
    """Get application settings"""
    try:
        openrag_config = get_openrag_config()

        provider_config = openrag_config.provider
        knowledge_config = openrag_config.knowledge
        agent_config = openrag_config.agent
        # Return public settings that are safe to expose to frontend
        settings = {
            "langflow_url": LANGFLOW_URL,
            "flow_id": LANGFLOW_CHAT_FLOW_ID,
            "ingest_flow_id": LANGFLOW_INGEST_FLOW_ID,
            "langflow_public_url": LANGFLOW_PUBLIC_URL,
            "edited": openrag_config.edited,
            # OpenRAG configuration
            "provider": {
                "model_provider": provider_config.model_provider,
                # Note: API key is not exposed for security
            },
            "knowledge": {
                "embedding_model": knowledge_config.embedding_model,
                "chunk_size": knowledge_config.chunk_size,
                "chunk_overlap": knowledge_config.chunk_overlap,
                "ocr": knowledge_config.ocr,
                "picture_descriptions": knowledge_config.picture_descriptions,
            },
            "agent": {
                "llm_model": agent_config.llm_model,
                "system_prompt": agent_config.system_prompt,
            },
        }

        # Only expose edit URLs when a public URL is configured
        if LANGFLOW_PUBLIC_URL and LANGFLOW_CHAT_FLOW_ID:
            settings["langflow_edit_url"] = (
                f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_CHAT_FLOW_ID}"
            )

        if LANGFLOW_PUBLIC_URL and LANGFLOW_INGEST_FLOW_ID:
            settings["langflow_ingest_edit_url"] = (
                f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_INGEST_FLOW_ID}"
            )

        # Fetch ingestion flow configuration to get actual component defaults
        if LANGFLOW_INGEST_FLOW_ID and openrag_config.edited:
            try:
                response = await clients.langflow_request(
                    "GET",
                    f"/api/v1/flows/{LANGFLOW_INGEST_FLOW_ID}"
                )
                if response.status_code == 200:
                    flow_data = response.json()

                    # Extract component defaults (ingestion-specific settings only)
                    # Start with configured defaults
                    ingestion_defaults = {
                        "chunkSize": knowledge_config.chunk_size,
                        "chunkOverlap": knowledge_config.chunk_overlap,
                        "separator": "\\n",  # Keep hardcoded for now as it's not in config
                        "embeddingModel": knowledge_config.embedding_model,
                    }

                    if flow_data.get("data", {}).get("nodes"):
                        for node in flow_data["data"]["nodes"]:
                            node_template = (
                                node.get("data", {})
                                .get("node", {})
                                .get("template", {})
                            )

                            # Split Text component (SplitText-QIKhg)
                            if node.get("id") == "SplitText-QIKhg":
                                if node_template.get("chunk_size", {}).get(
                                    "value"
                                ):
                                    ingestion_defaults["chunkSize"] = (
                                        node_template["chunk_size"]["value"]
                                    )
                                if node_template.get("chunk_overlap", {}).get(
                                    "value"
                                ):
                                    ingestion_defaults["chunkOverlap"] = (
                                        node_template["chunk_overlap"]["value"]
                                    )
                                if node_template.get("separator", {}).get(
                                    "value"
                                ):
                                    ingestion_defaults["separator"] = (
                                        node_template["separator"]["value"]
                                    )

                            # OpenAI Embeddings component (OpenAIEmbeddings-joRJ6)
                            elif node.get("id") == "OpenAIEmbeddings-joRJ6":
                                if node_template.get("model", {}).get("value"):
                                    ingestion_defaults["embeddingModel"] = (
                                        node_template["model"]["value"]
                                    )

                            # Note: OpenSearch component settings are not exposed for ingestion
                            # (search-related parameters like number_of_results, score_threshold
                            # are for retrieval, not ingestion)

                    settings["ingestion_defaults"] = ingestion_defaults

            except Exception as e:
                logger.warning(f"Failed to fetch ingestion flow defaults: {e}")
                # Continue without ingestion defaults

        return JSONResponse(settings)

    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to retrieve settings: {str(e)}"}, status_code=500
        )


async def update_settings(request, session_manager):
    """Update application settings"""
    try:
        # Get current configuration
        current_config = get_openrag_config()
        
        # Check if config is marked as edited
        if not current_config.edited:
            return JSONResponse(
                {"error": "Configuration must be marked as edited before updates are allowed"}, 
                status_code=403
            )
        
        # Parse request body
        body = await request.json()
        
        # Validate allowed fields
        allowed_fields = {
            "llm_model", "system_prompt", "ocr", "picture_descriptions", 
            "chunk_size", "chunk_overlap"
        }
        
        # Check for invalid fields
        invalid_fields = set(body.keys()) - allowed_fields
        if invalid_fields:
            return JSONResponse(
                {"error": f"Invalid fields: {', '.join(invalid_fields)}. Allowed fields: {', '.join(allowed_fields)}"}, 
                status_code=400
            )
        
        # Update configuration
        config_updated = False
        
        # Update agent settings
        if "llm_model" in body:
            current_config.agent.llm_model = body["llm_model"]
            config_updated = True
            
        if "system_prompt" in body:
            current_config.agent.system_prompt = body["system_prompt"]
            config_updated = True
        
        # Update knowledge settings
        if "ocr" in body:
            if not isinstance(body["ocr"], bool):
                return JSONResponse(
                    {"error": "ocr must be a boolean value"}, 
                    status_code=400
                )
            current_config.knowledge.ocr = body["ocr"]
            config_updated = True
            
        if "picture_descriptions" in body:
            if not isinstance(body["picture_descriptions"], bool):
                return JSONResponse(
                    {"error": "picture_descriptions must be a boolean value"}, 
                    status_code=400
                )
            current_config.knowledge.picture_descriptions = body["picture_descriptions"]
            config_updated = True
            
        if "chunk_size" in body:
            if not isinstance(body["chunk_size"], int) or body["chunk_size"] <= 0:
                return JSONResponse(
                    {"error": "chunk_size must be a positive integer"}, 
                    status_code=400
                )
            current_config.knowledge.chunk_size = body["chunk_size"]
            config_updated = True
            
        if "chunk_overlap" in body:
            if not isinstance(body["chunk_overlap"], int) or body["chunk_overlap"] < 0:
                return JSONResponse(
                    {"error": "chunk_overlap must be a non-negative integer"}, 
                    status_code=400
                )
            current_config.knowledge.chunk_overlap = body["chunk_overlap"]
            config_updated = True
        
        if not config_updated:
            return JSONResponse(
                {"error": "No valid fields provided for update"}, 
                status_code=400
            )
        
        # Save the updated configuration
        if config_manager.save_config_file(current_config):
            logger.info("Configuration updated successfully", updated_fields=list(body.keys()))
            return JSONResponse({"message": "Configuration updated successfully"})
        else:
            return JSONResponse(
                {"error": "Failed to save configuration"}, 
                status_code=500
            )
        
    except Exception as e:
        logger.error("Failed to update settings", error=str(e))
        return JSONResponse(
            {"error": f"Failed to update settings: {str(e)}"}, status_code=500
        )
