import json
import platform
import time
from starlette.responses import JSONResponse
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger
from config.settings import (
    DISABLE_INGEST_WITH_LANGFLOW,
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    LANGFLOW_PUBLIC_URL,
    LOCALHOST_URL,
    clients,
    get_openrag_config,
    config_manager,
)

logger = get_logger(__name__)


# Docling preset configurations
def get_docling_preset_configs(table_structure=False, ocr=False, picture_descriptions=False):
    """Get docling preset configurations based on toggle settings

    Args:
        table_structure: Enable table structure parsing (default: False)
        ocr: Enable OCR for text extraction from images (default: False)
        picture_descriptions: Enable picture descriptions/captions (default: False)
    """
    is_macos = platform.system() == "Darwin"

    config = {
        "do_ocr": ocr,
        "ocr_engine": "ocrmac" if is_macos else "easyocr",
        "do_table_structure": table_structure,
        "do_picture_classification": picture_descriptions,
        "do_picture_description": picture_descriptions,
        "picture_description_local": {
            "repo_id": "HuggingFaceTB/SmolVLM-256M-Instruct",
            "prompt": "Describe this image in a few sentences.",
        }
    }

    return config


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
                "endpoint": provider_config.endpoint if provider_config.endpoint else None,
                "project_id": provider_config.project_id if provider_config.project_id else None,
                # Note: API key is not exposed for security
            },
            "knowledge": {
                "embedding_model": knowledge_config.embedding_model,
                "chunk_size": knowledge_config.chunk_size,
                "chunk_overlap": knowledge_config.chunk_overlap,
                "table_structure": knowledge_config.table_structure,
                "ocr": knowledge_config.ocr,
                "picture_descriptions": knowledge_config.picture_descriptions,
            },
            "agent": {
                "llm_model": agent_config.llm_model,
                "system_prompt": agent_config.system_prompt,
            },
            "localhost_url": LOCALHOST_URL,
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
            "table_structure",
            "ocr",
            "picture_descriptions",
            "embedding_model",
            "model_provider",
            "api_key",
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

        # Update agent settings
        if "llm_model" in body:
            current_config.agent.llm_model = body["llm_model"]
            config_updated = True

            # Also update the chat flow with the new model
            try:
                flows_service = _get_flows_service()
                await flows_service.update_chat_flow_model(body["llm_model"], current_config.provider.model_provider.lower())
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
                    body["system_prompt"],
                    current_config.agent.system_prompt
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
            new_embedding_model = body["embedding_model"].strip()
            current_config.knowledge.embedding_model = new_embedding_model
            config_updated = True

            # Also update the ingest flow with the new embedding model
            try:
                flows_service = _get_flows_service()
                await flows_service.update_ingest_flow_embedding_model(
                    new_embedding_model,
                    current_config.provider.model_provider.lower()
                )
                logger.info(
                    f"Successfully updated ingest flow embedding model to '{body['embedding_model'].strip()}'"
                )

                provider = (
                    current_config.provider.model_provider.lower()
                    if current_config.provider.model_provider
                    else "openai"
                )
                endpoint = current_config.provider.endpoint or None
                llm_model = current_config.agent.llm_model

                change_result = await flows_service.change_langflow_model_value(
                    provider=provider,
                    embedding_model=new_embedding_model,
                    llm_model=llm_model,
                    endpoint=endpoint,
                )

                if not change_result.get("success", False):
                    logger.warning(
                        "Change embedding model across flows completed with issues",
                        provider=provider,
                        embedding_model=new_embedding_model,
                        change_result=change_result,
                    )
                else:
                    logger.info(
                        "Successfully updated embedding model across Langflow flows",
                        provider=provider,
                        embedding_model=new_embedding_model,
                    )
            except Exception as e:
                logger.error(f"Failed to update ingest flow embedding model: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        if "table_structure" in body:
            if not isinstance(body["table_structure"], bool):
                return JSONResponse(
                    {"error": "table_structure must be a boolean"}, status_code=400
                )
            current_config.knowledge.table_structure = body["table_structure"]
            config_updated = True

            # Also update the flow with the new docling settings
            try:
                flows_service = _get_flows_service()
                preset_config = get_docling_preset_configs(
                    table_structure=body["table_structure"],
                    ocr=current_config.knowledge.ocr,
                    picture_descriptions=current_config.knowledge.picture_descriptions
                )
                await flows_service.update_flow_docling_preset("custom", preset_config)
                logger.info(f"Successfully updated table_structure setting in flow")
            except Exception as e:
                logger.error(f"Failed to update docling settings in flow: {str(e)}")

        if "ocr" in body:
            if not isinstance(body["ocr"], bool):
                return JSONResponse(
                    {"error": "ocr must be a boolean"}, status_code=400
                )
            current_config.knowledge.ocr = body["ocr"]
            config_updated = True

            # Also update the flow with the new docling settings
            try:
                flows_service = _get_flows_service()
                preset_config = get_docling_preset_configs(
                    table_structure=current_config.knowledge.table_structure,
                    ocr=body["ocr"],
                    picture_descriptions=current_config.knowledge.picture_descriptions
                )
                await flows_service.update_flow_docling_preset("custom", preset_config)
                logger.info(f"Successfully updated ocr setting in flow")
            except Exception as e:
                logger.error(f"Failed to update docling settings in flow: {str(e)}")

        if "picture_descriptions" in body:
            if not isinstance(body["picture_descriptions"], bool):
                return JSONResponse(
                    {"error": "picture_descriptions must be a boolean"}, status_code=400
                )
            current_config.knowledge.picture_descriptions = body["picture_descriptions"]
            config_updated = True

            # Also update the flow with the new docling settings
            try:
                flows_service = _get_flows_service()
                preset_config = get_docling_preset_configs(
                    table_structure=current_config.knowledge.table_structure,
                    ocr=current_config.knowledge.ocr,
                    picture_descriptions=body["picture_descriptions"]
                )
                await flows_service.update_flow_docling_preset("custom", preset_config)
                logger.info(f"Successfully updated picture_descriptions setting in flow")
            except Exception as e:
                logger.error(f"Failed to update docling settings in flow: {str(e)}")

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
            # Only update if non-empty string (empty string means keep current value)
            if body["api_key"].strip():
                current_config.provider.api_key = body["api_key"]
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

        if not config_updated:
            return JSONResponse(
                {"error": "No valid fields provided for update"}, status_code=400
            )

        # Save the updated configuration
        if not config_manager.save_config_file(current_config):
            return JSONResponse(
                {"error": "Failed to save configuration"}, status_code=500
            )

        # Update Langflow global variables if provider settings changed
        if any(key in body for key in ["model_provider", "api_key", "endpoint", "project_id"]):
            try:
                provider = current_config.provider.model_provider.lower() if current_config.provider.model_provider else "openai"
                
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
                    logger.info("Set WATSONX_PROJECT_ID global variable in Langflow")

                # Set API key for OpenAI provider
                if provider == "openai" and "api_key" in body:
                    api_key = body["api_key"]
                    await clients._create_langflow_global_variable(
                        "OPENAI_API_KEY", api_key, modify=True
                    )
                    logger.info("Set OPENAI_API_KEY global variable in Langflow")

                # Set base URL for Ollama provider
                if provider == "ollama" and "endpoint" in body:
                    endpoint = transform_localhost_url(body["endpoint"])
                    await clients._create_langflow_global_variable(
                        "OLLAMA_BASE_URL", endpoint, modify=True
                    )
                    logger.info("Set OLLAMA_BASE_URL global variable in Langflow")

                # Update model values across flows if provider changed
                if "model_provider" in body:
                    flows_service = _get_flows_service()
                    await flows_service.change_langflow_model_value(
                        provider,
                        current_config.knowledge.embedding_model,
                        current_config.agent.llm_model,
                        current_config.provider.endpoint,
                    )
                    logger.info(f"Successfully updated Langflow flows for provider {provider}")

            except Exception as e:
                logger.error(f"Failed to update Langflow settings: {str(e)}")
                # Don't fail the entire settings update if Langflow update fails
                # The config was still saved

        logger.info(
            "Configuration updated successfully", updated_fields=list(body.keys())
        )
        return JSONResponse({"message": "Configuration updated successfully"})

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

        # Warn if config was already edited (onboarding being re-run)
        if current_config.edited:
            logger.warning(
                "Onboarding is being run although configuration was already edited before"
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

        # Validate provider setup before initializing OpenSearch index
        try:
            from api.provider_validation import validate_provider_setup

            provider = current_config.provider.model_provider.lower() if current_config.provider.model_provider else "openai"

            logger.info(f"Validating provider setup for {provider}")
            await validate_provider_setup(
                provider=provider,
                api_key=current_config.provider.api_key,
                embedding_model=current_config.knowledge.embedding_model,
                llm_model=current_config.agent.llm_model,
                endpoint=current_config.provider.endpoint,
                project_id=current_config.provider.project_id,
            )
            logger.info(f"Provider setup validation completed successfully for {provider}")
        except Exception as e:
            logger.error(f"Provider validation failed: {str(e)}")
            return JSONResponse(
                {"error": str(e)},
                status_code=400,
            )

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
            if isinstance(e, ValueError):
                logger.error(
                    "Failed to initialize OpenSearch index after onboarding",
                    error=str(e),
                )
                return JSONResponse(
                    {
                        "error": str(e),
                        "edited": True,
                    },
                    status_code=400,
                )
            logger.error(
                "Failed to initialize OpenSearch index after onboarding",
                error=str(e),
            )
            # Don't fail the entire onboarding process if index creation fails
            # The application can still work, but document operations may fail

        # Save the updated configuration (this will mark it as edited)
        
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
                raise

            # Set Langflow global variables based on provider
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
                    endpoint = transform_localhost_url(body["endpoint"])

                    await clients._create_langflow_global_variable(
                        "OLLAMA_BASE_URL", endpoint, modify=True
                    )
                    logger.info("Set OLLAMA_BASE_URL global variable in Langflow")

                await flows_service.change_langflow_model_value(
                    provider,
                    body.get("embedding_model"),
                    body.get("llm_model"),
                    body.get("endpoint"),
                )

            except Exception as e:
                logger.error(
                    "Failed to set Langflow global variables",
                    provider=provider,
                    error=str(e),
                )
                raise

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
        if config_manager.save_config_file(current_config):
            updated_fields = [
                k for k in body.keys() if k != "sample_data"
            ]  # Exclude sample_data from log
            logger.info(
                "Onboarding configuration updated successfully",
                updated_fields=updated_fields,
            )

        else:
            return JSONResponse(
                {"error": "Failed to save configuration"}, status_code=500
            )

        return JSONResponse(
            {
                "message": "Onboarding configuration updated successfully",
                "edited": True,  # Confirm that config is now marked as edited
                "sample_data_ingested": should_ingest_sample_data,
            }
        )

    except Exception as e:
        logger.error("Failed to update onboarding settings", error=str(e))
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


def _get_flows_service():
    """Helper function to get flows service instance"""
    from services.flows_service import FlowsService

    return FlowsService()


async def update_docling_preset(request, session_manager):
    """Update docling settings in the ingest flow - deprecated endpoint, use /settings instead"""
    try:
        # Parse request body
        body = await request.json()

        # Support old preset-based API for backwards compatibility
        if "preset" in body:
            # Map old presets to new toggle settings
            preset_map = {
                "standard": {"table_structure": False, "ocr": False, "picture_descriptions": False},
                "ocr": {"table_structure": False, "ocr": True, "picture_descriptions": False},
                "picture_description": {"table_structure": False, "ocr": True, "picture_descriptions": True},
                "VLM": {"table_structure": False, "ocr": False, "picture_descriptions": False},
            }

            preset = body["preset"]
            if preset not in preset_map:
                return JSONResponse(
                    {"error": f"Invalid preset '{preset}'. Valid presets: {', '.join(preset_map.keys())}"},
                    status_code=400,
                )

            settings = preset_map[preset]
        else:
            # Support new toggle-based API
            settings = {
                "table_structure": body.get("table_structure", False),
                "ocr": body.get("ocr", False),
                "picture_descriptions": body.get("picture_descriptions", False),
            }

        # Get the preset configuration
        preset_config = get_docling_preset_configs(**settings)

        # Use the helper function to update the flow
        flows_service = _get_flows_service()
        await flows_service.update_flow_docling_preset("custom", preset_config)

        logger.info(f"Successfully updated docling settings in ingest flow")

        return JSONResponse(
            {
                "message": f"Successfully updated docling settings",
                "settings": settings,
                "preset_config": preset_config,
            }
        )

    except Exception as e:
        logger.error("Failed to update docling settings", error=str(e))
        return JSONResponse(
            {"error": f"Failed to update docling settings: {str(e)}"}, status_code=500
        )
