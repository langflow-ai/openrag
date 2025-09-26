import json
import platform
from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import (
    DISABLE_INGEST_WITH_LANGFLOW,
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    LANGFLOW_PUBLIC_URL,
    DOCLING_COMPONENT_ID,
    clients,
    get_openrag_config,
    config_manager,
)

logger = get_logger(__name__)


# Docling preset configurations
def get_docling_preset_configs():
    """Get docling preset configurations with platform-specific settings"""
    is_macos = platform.system() == "Darwin"

    return {
        "standard": {"do_ocr": False},
        "ocr": {"do_ocr": True, "ocr_engine": "ocrmac" if is_macos else "easyocr"},
        "picture_description": {
            "do_ocr": True,
            "ocr_engine": "ocrmac" if is_macos else "easyocr",
            "do_picture_classification": True,
            "do_picture_description": True,
            "picture_description_local": {
                "repo_id": "HuggingFaceTB/SmolVLM-256M-Instruct",
                "prompt": "Describe this image in a few sentences.",
            },
        },
        "VLM": {
            "pipeline": "vlm",
            "vlm_pipeline_model_local": {
                "repo_id": "ds4sd/SmolDocling-256M-preview-mlx-bf16"
                if is_macos
                else "ds4sd/SmolDocling-256M-preview",
                "response_format": "doctags",
                "inference_framework": "mlx",
            },
        },
    }


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
                "doclingPresets": knowledge_config.doclingPresets,
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
                    "GET", f"/api/v1/flows/{LANGFLOW_INGEST_FLOW_ID}"
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
                                node.get("data", {}).get("node", {}).get("template", {})
                            )

                            # Split Text component (SplitText-QIKhg)
                            if node.get("id") == "SplitText-QIKhg":
                                if node_template.get("chunk_size", {}).get("value"):
                                    ingestion_defaults["chunkSize"] = node_template[
                                        "chunk_size"
                                    ]["value"]
                                if node_template.get("chunk_overlap", {}).get("value"):
                                    ingestion_defaults["chunkOverlap"] = node_template[
                                        "chunk_overlap"
                                    ]["value"]
                                if node_template.get("separator", {}).get("value"):
                                    ingestion_defaults["separator"] = node_template[
                                        "separator"
                                    ]["value"]

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
                {
                    "error": "Configuration must be marked as edited before updates are allowed"
                },
                status_code=403,
            )

        # Parse request body
        body = await request.json()

        # Validate allowed fields
        allowed_fields = {
            "llm_model",
            "system_prompt",
            "chunk_size",
            "chunk_overlap",
            "doclingPresets",
            "embedding_model",
        }

        # Check for invalid fields
        invalid_fields = set(body.keys()) - allowed_fields
        if invalid_fields:
            return JSONResponse(
                {
                    "error": f"Invalid fields: {', '.join(invalid_fields)}. Allowed fields: {', '.join(allowed_fields)}"
                },
                status_code=400,
            )

        # Update configuration
        config_updated = False

        # Update agent settings
        if "llm_model" in body:
            current_config.agent.llm_model = body["llm_model"]
            config_updated = True

            # Also update the chat flow with the new model
            try:
                flows_service = _get_flows_service()
                await flows_service.update_chat_flow_model(body["llm_model"])
                logger.info(
                    f"Successfully updated chat flow model to '{body['llm_model']}'"
                )
            except Exception as e:
                logger.error(f"Failed to update chat flow model: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        if "system_prompt" in body:
            current_config.agent.system_prompt = body["system_prompt"]
            config_updated = True

            # Also update the chat flow with the new system prompt
            try:
                flows_service = _get_flows_service()
                await flows_service.update_chat_flow_system_prompt(
                    body["system_prompt"]
                )
                logger.info(f"Successfully updated chat flow system prompt")
            except Exception as e:
                logger.error(f"Failed to update chat flow system prompt: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        # Update knowledge settings
        if "embedding_model" in body:
            if (
                not isinstance(body["embedding_model"], str)
                or not body["embedding_model"].strip()
            ):
                return JSONResponse(
                    {"error": "embedding_model must be a non-empty string"},
                    status_code=400,
                )
            current_config.knowledge.embedding_model = body["embedding_model"].strip()
            config_updated = True

            # Also update the ingest flow with the new embedding model
            try:
                flows_service = _get_flows_service()
                await flows_service.update_ingest_flow_embedding_model(
                    body["embedding_model"].strip()
                )
                logger.info(
                    f"Successfully updated ingest flow embedding model to '{body['embedding_model'].strip()}'"
                )
            except Exception as e:
                logger.error(f"Failed to update ingest flow embedding model: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        if "doclingPresets" in body:
            preset_configs = get_docling_preset_configs()
            valid_presets = list(preset_configs.keys())
            if body["doclingPresets"] not in valid_presets:
                return JSONResponse(
                    {
                        "error": f"doclingPresets must be one of: {', '.join(valid_presets)}"
                    },
                    status_code=400,
                )
            current_config.knowledge.doclingPresets = body["doclingPresets"]
            config_updated = True

            # Also update the flow with the new docling preset
            try:
                flows_service = _get_flows_service()
                await flows_service.update_flow_docling_preset(
                    body["doclingPresets"], preset_configs[body["doclingPresets"]]
                )
                logger.info(
                    f"Successfully updated docling preset in flow to '{body['doclingPresets']}'"
                )
            except Exception as e:
                logger.error(f"Failed to update docling preset in flow: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        if "chunk_size" in body:
            if not isinstance(body["chunk_size"], int) or body["chunk_size"] <= 0:
                return JSONResponse(
                    {"error": "chunk_size must be a positive integer"}, status_code=400
                )
            current_config.knowledge.chunk_size = body["chunk_size"]
            config_updated = True

            # Also update the ingest flow with the new chunk size
            try:
                flows_service = _get_flows_service()
                await flows_service.update_ingest_flow_chunk_size(body["chunk_size"])
                logger.info(
                    f"Successfully updated ingest flow chunk size to {body['chunk_size']}"
                )
            except Exception as e:
                logger.error(f"Failed to update ingest flow chunk size: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        if "chunk_overlap" in body:
            if not isinstance(body["chunk_overlap"], int) or body["chunk_overlap"] < 0:
                return JSONResponse(
                    {"error": "chunk_overlap must be a non-negative integer"},
                    status_code=400,
                )
            current_config.knowledge.chunk_overlap = body["chunk_overlap"]
            config_updated = True

            # Also update the ingest flow with the new chunk overlap
            try:
                flows_service = _get_flows_service()
                await flows_service.update_ingest_flow_chunk_overlap(
                    body["chunk_overlap"]
                )
                logger.info(
                    f"Successfully updated ingest flow chunk overlap to {body['chunk_overlap']}"
                )
            except Exception as e:
                logger.error(f"Failed to update ingest flow chunk overlap: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        if not config_updated:
            return JSONResponse(
                {"error": "No valid fields provided for update"}, status_code=400
            )

        # Save the updated configuration
        if config_manager.save_config_file(current_config):
            logger.info(
                "Configuration updated successfully", updated_fields=list(body.keys())
            )
            return JSONResponse({"message": "Configuration updated successfully"})
        else:
            return JSONResponse(
                {"error": "Failed to save configuration"}, status_code=500
            )

    except Exception as e:
        logger.error("Failed to update settings", error=str(e))
        return JSONResponse(
            {"error": f"Failed to update settings: {str(e)}"}, status_code=500
        )


async def onboarding(request, flows_service):
    """Handle onboarding configuration setup"""
    try:
        # Get current configuration
        current_config = get_openrag_config()

        # Check if config is NOT marked as edited (only allow onboarding if not yet configured)
        if current_config.edited:
            return JSONResponse(
                {
                    "error": "Configuration has already been edited. Use /settings endpoint for updates."
                },
                status_code=403,
            )

        # Parse request body
        body = await request.json()

        # Validate allowed fields
        allowed_fields = {
            "model_provider",
            "api_key",
            "embedding_model",
            "llm_model",
            "sample_data",
            "endpoint",
            "project_id",
        }

        # Check for invalid fields
        invalid_fields = set(body.keys()) - allowed_fields
        if invalid_fields:
            return JSONResponse(
                {
                    "error": f"Invalid fields: {', '.join(invalid_fields)}. Allowed fields: {', '.join(allowed_fields)}"
                },
                status_code=400,
            )

        # Update configuration
        config_updated = False

        # Update provider settings
        if "model_provider" in body:
            if (
                not isinstance(body["model_provider"], str)
                or not body["model_provider"].strip()
            ):
                return JSONResponse(
                    {"error": "model_provider must be a non-empty string"},
                    status_code=400,
                )
            current_config.provider.model_provider = body["model_provider"].strip()
            config_updated = True

        if "api_key" in body:
            if not isinstance(body["api_key"], str):
                return JSONResponse(
                    {"error": "api_key must be a string"}, status_code=400
                )
            current_config.provider.api_key = body["api_key"]
            config_updated = True

        # Update knowledge settings
        if "embedding_model" in body and not DISABLE_INGEST_WITH_LANGFLOW:
            if (
                not isinstance(body["embedding_model"], str)
                or not body["embedding_model"].strip()
            ):
                return JSONResponse(
                    {"error": "embedding_model must be a non-empty string"},
                    status_code=400,
                )
            current_config.knowledge.embedding_model = body["embedding_model"].strip()
            config_updated = True

        # Update agent settings
        if "llm_model" in body:
            if not isinstance(body["llm_model"], str) or not body["llm_model"].strip():
                return JSONResponse(
                    {"error": "llm_model must be a non-empty string"}, status_code=400
                )
            current_config.agent.llm_model = body["llm_model"].strip()
            config_updated = True

        if "endpoint" in body:
            if not isinstance(body["endpoint"], str) or not body["endpoint"].strip():
                return JSONResponse(
                    {"error": "endpoint must be a non-empty string"}, status_code=400
                )
            current_config.provider.endpoint = body["endpoint"].strip()
            config_updated = True

        if "project_id" in body:
            if (
                not isinstance(body["project_id"], str)
                or not body["project_id"].strip()
            ):
                return JSONResponse(
                    {"error": "project_id must be a non-empty string"}, status_code=400
                )
            current_config.provider.project_id = body["project_id"].strip()
            config_updated = True

        # Handle sample_data
        should_ingest_sample_data = False
        if "sample_data" in body:
            if not isinstance(body["sample_data"], bool):
                return JSONResponse(
                    {"error": "sample_data must be a boolean value"}, status_code=400
                )
            should_ingest_sample_data = body["sample_data"]

        if not config_updated:
            return JSONResponse(
                {"error": "No valid fields provided for update"}, status_code=400
            )

        # Save the updated configuration (this will mark it as edited)
        if config_manager.save_config_file(current_config):
            updated_fields = [
                k for k in body.keys() if k != "sample_data"
            ]  # Exclude sample_data from log
            logger.info(
                "Onboarding configuration updated successfully",
                updated_fields=updated_fields,
            )

            # If model_provider was updated, assign the new provider to flows
            if "model_provider" in body:
                provider = body["model_provider"].strip().lower()
                try:
                    flow_result = await flows_service.assign_model_provider(provider)

                    if flow_result.get("success"):
                        logger.info(
                            f"Successfully assigned {provider} to flows",
                            flow_result=flow_result,
                        )
                    else:
                        logger.warning(
                            f"Failed to assign {provider} to flows",
                            flow_result=flow_result,
                        )
                        # Continue even if flow assignment fails - configuration was still saved

                except Exception as e:
                    logger.error(
                        "Error assigning model provider to flows",
                        provider=provider,
                        error=str(e),
                    )
                    # Continue even if flow assignment fails - configuration was still saved

            # Set Langflow global variables based on provider
            if "model_provider" in body:
                provider = body["model_provider"].strip().lower()

                try:
                    # Set API key for IBM/Watson providers
                    if (provider == "watsonx") and "api_key" in body:
                        api_key = body["api_key"]
                        await clients._create_langflow_global_variable(
                            "WATSONX_API_KEY", api_key, modify=True
                        )
                        logger.info("Set WATSONX_API_KEY global variable in Langflow")

                    # Set project ID for IBM/Watson providers
                    if (provider == "watsonx") and "project_id" in body:
                        project_id = body["project_id"]
                        await clients._create_langflow_global_variable(
                            "WATSONX_PROJECT_ID", project_id, modify=True
                        )
                        logger.info(
                            "Set WATSONX_PROJECT_ID global variable in Langflow"
                        )

                    # Set API key for OpenAI provider
                    if provider == "openai" and "api_key" in body:
                        api_key = body["api_key"]
                        await clients._create_langflow_global_variable(
                            "OPENAI_API_KEY", api_key, modify=True
                        )
                        logger.info("Set OPENAI_API_KEY global variable in Langflow")

                    # Set base URL for Ollama provider
                    if provider == "ollama" and "endpoint" in body:
                        endpoint = body["endpoint"]
                        await clients._create_langflow_global_variable(
                            "OLLAMA_BASE_URL", endpoint, modify=True
                        )
                        logger.info("Set OLLAMA_BASE_URL global variable in Langflow")

                    await flows_service.change_langflow_model_value(
                        provider,
                        body["embedding_model"],
                        body["llm_model"],
                        body["endpoint"],
                    )

                except Exception as e:
                    logger.error(
                        "Failed to set Langflow global variables",
                        provider=provider,
                        error=str(e),
                    )
                    # Continue even if setting global variables fails

            # Initialize the OpenSearch index now that we have the embedding model configured
            try:
                # Import here to avoid circular imports
                from main import init_index

                logger.info(
                    "Initializing OpenSearch index after onboarding configuration"
                )
                await init_index()
                logger.info("OpenSearch index initialization completed successfully")
            except Exception as e:
                logger.error(
                    "Failed to initialize OpenSearch index after onboarding",
                    error=str(e),
                )
                # Don't fail the entire onboarding process if index creation fails
                # The application can still work, but document operations may fail

            # Handle sample data ingestion if requested
            if should_ingest_sample_data:
                try:
                    # Import the function here to avoid circular imports
                    from main import ingest_default_documents_when_ready

                    # Get services from the current app state
                    # We need to access the app instance to get services
                    app = request.scope.get("app")
                    if app and hasattr(app.state, "services"):
                        services = app.state.services
                        logger.info(
                            "Starting sample data ingestion as requested in onboarding"
                        )
                        await ingest_default_documents_when_ready(services)
                        logger.info("Sample data ingestion completed successfully")
                    else:
                        logger.error(
                            "Could not access services for sample data ingestion"
                        )

                except Exception as e:
                    logger.error(
                        "Failed to complete sample data ingestion", error=str(e)
                    )
                    # Don't fail the entire onboarding process if sample data fails

            return JSONResponse(
                {
                    "message": "Onboarding configuration updated successfully",
                    "edited": True,  # Confirm that config is now marked as edited
                    "sample_data_ingested": should_ingest_sample_data,
                }
            )
        else:
            return JSONResponse(
                {"error": "Failed to save configuration"}, status_code=500
            )

    except Exception as e:
        logger.error("Failed to update onboarding settings", error=str(e))
        return JSONResponse(
            {"error": f"Failed to update onboarding settings: {str(e)}"},
            status_code=500,
        )


def _get_flows_service():
    """Helper function to get flows service instance"""
    from services.flows_service import FlowsService

    return FlowsService()


async def update_docling_preset(request, session_manager):
    """Update docling preset in the ingest flow"""
    try:
        # Parse request body
        body = await request.json()

        # Validate preset parameter
        if "preset" not in body:
            return JSONResponse(
                {"error": "preset parameter is required"}, status_code=400
            )

        preset = body["preset"]
        preset_configs = get_docling_preset_configs()

        if preset not in preset_configs:
            valid_presets = list(preset_configs.keys())
            return JSONResponse(
                {
                    "error": f"Invalid preset '{preset}'. Valid presets: {', '.join(valid_presets)}"
                },
                status_code=400,
            )

        # Get the preset configuration
        preset_config = preset_configs[preset]

        # Use the helper function to update the flow
        flows_service = _get_flows_service()
        await flows_service.update_flow_docling_preset(preset, preset_config)

        logger.info(f"Successfully updated docling preset to '{preset}' in ingest flow")

        return JSONResponse(
            {
                "message": f"Successfully updated docling preset to '{preset}'",
                "preset": preset,
                "preset_config": preset_config,
            }
        )

    except Exception as e:
        logger.error("Failed to update docling preset", error=str(e))
        return JSONResponse(
            {"error": f"Failed to update docling preset: {str(e)}"}, status_code=500
        )
