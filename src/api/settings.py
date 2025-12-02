import json
import platform
import time
from starlette.responses import JSONResponse
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger
from utils.telemetry import TelemetryClient, Category, MessageId
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
    is_no_auth_mode,
)
from api.provider_validation import validate_provider_setup

logger = get_logger(__name__)


# Docling preset configurations
def get_docling_preset_configs(
    table_structure=False, ocr=False, picture_descriptions=False
):
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
        },
    }

    return config


async def get_settings(request, session_manager):
    """Get application settings"""
    try:
        openrag_config = get_openrag_config()

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
            "providers": {
                "openai": {
                    "has_api_key": bool(openrag_config.providers.openai.api_key),
                    "configured": openrag_config.providers.openai.configured,
                    # Note: API key is not exposed for security
                },
                "anthropic": {
                    "has_api_key": bool(openrag_config.providers.anthropic.api_key),
                    "configured": openrag_config.providers.anthropic.configured,
                },
                "watsonx": {
                    "has_api_key": bool(openrag_config.providers.watsonx.api_key),
                    "endpoint": openrag_config.providers.watsonx.endpoint or None,
                    "project_id": openrag_config.providers.watsonx.project_id or None,
                    "configured": openrag_config.providers.watsonx.configured,
                },
                "ollama": {
                    "endpoint": openrag_config.providers.ollama.endpoint or None,
                    "configured": openrag_config.providers.ollama.configured,
                },
            },
            "knowledge": {
                "embedding_model": knowledge_config.embedding_model,
                "embedding_provider": knowledge_config.embedding_provider,
                "chunk_size": knowledge_config.chunk_size,
                "chunk_overlap": knowledge_config.chunk_overlap,
                "table_structure": knowledge_config.table_structure,
                "ocr": knowledge_config.ocr,
                "picture_descriptions": knowledge_config.picture_descriptions,
            },
            "agent": {
                "llm_model": agent_config.llm_model,
                "llm_provider": agent_config.llm_provider,
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
            "llm_provider",
            "system_prompt",
            "chunk_size",
            "chunk_overlap",
            "table_structure",
            "ocr",
            "picture_descriptions",
            "embedding_model",
            "embedding_provider",
            # Provider-specific fields (structured as provider_name.field_name)
            "openai_api_key",
            "anthropic_api_key",
            "watsonx_api_key",
            "watsonx_endpoint",
            "watsonx_project_id",
            "ollama_endpoint",
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

        # Validate types early before modifying config
        if "embedding_model" in body:
            if (
                not isinstance(body["embedding_model"], str)
                or not body["embedding_model"].strip()
            ):
                return JSONResponse(
                    {"error": "embedding_model must be a non-empty string"},
                    status_code=400,
                )

        if "table_structure" in body:
            if not isinstance(body["table_structure"], bool):
                return JSONResponse(
                    {"error": "table_structure must be a boolean"}, status_code=400
                )

        if "ocr" in body:
            if not isinstance(body["ocr"], bool):
                return JSONResponse({"error": "ocr must be a boolean"}, status_code=400)

        if "picture_descriptions" in body:
            if not isinstance(body["picture_descriptions"], bool):
                return JSONResponse(
                    {"error": "picture_descriptions must be a boolean"}, status_code=400
                )

        if "chunk_size" in body:
            if not isinstance(body["chunk_size"], int) or body["chunk_size"] <= 0:
                return JSONResponse(
                    {"error": "chunk_size must be a positive integer"}, status_code=400
                )

        if "chunk_overlap" in body:
            if not isinstance(body["chunk_overlap"], int) or body["chunk_overlap"] < 0:
                return JSONResponse(
                    {"error": "chunk_overlap must be a non-negative integer"},
                    status_code=400,
                )

        if "llm_provider" in body:
            if (
                not isinstance(body["llm_provider"], str)
                or not body["llm_provider"].strip()
            ):
                return JSONResponse(
                    {"error": "llm_provider must be a non-empty string"},
                    status_code=400,
                )
            if body["llm_provider"] not in ["openai", "anthropic", "watsonx", "ollama"]:
                return JSONResponse(
                    {"error": "llm_provider must be one of: openai, anthropic, watsonx, ollama"},
                    status_code=400,
                )

        if "embedding_provider" in body:
            if (
                not isinstance(body["embedding_provider"], str)
                or not body["embedding_provider"].strip()
            ):
                return JSONResponse(
                    {"error": "embedding_provider must be a non-empty string"},
                    status_code=400,
                )
            # Anthropic doesn't have embeddings
            if body["embedding_provider"] not in ["openai", "watsonx", "ollama"]:
                return JSONResponse(
                    {"error": "embedding_provider must be one of: openai, watsonx, ollama"},
                    status_code=400,
                )

        # Validate provider-specific fields
        for key in ["openai_api_key", "anthropic_api_key", "watsonx_api_key"]:
            if key in body and not isinstance(body[key], str):
                return JSONResponse(
                    {"error": f"{key} must be a string"}, status_code=400
                )

        for key in ["watsonx_endpoint", "ollama_endpoint"]:
            if key in body:
                if not isinstance(body[key], str) or not body[key].strip():
                    return JSONResponse(
                        {"error": f"{key} must be a non-empty string"}, status_code=400
                    )

        if "watsonx_project_id" in body:
            if (
                not isinstance(body["watsonx_project_id"], str)
                or not body["watsonx_project_id"].strip()
            ):
                return JSONResponse(
                    {"error": "watsonx_project_id must be a non-empty string"}, status_code=400
                )

        # Validate provider setup if provider-related fields are being updated
        # Do this BEFORE modifying any config
        provider_fields = [
            "llm_provider",
            "embedding_provider",
            "llm_model",
            "embedding_model",
            "openai_api_key",
            "anthropic_api_key",
            "watsonx_api_key",
            "watsonx_endpoint",
            "watsonx_project_id",
            "ollama_endpoint",
        ]
        should_validate = any(field in body for field in provider_fields)

        if should_validate:
            try:
                logger.info("Running provider validation before modifying config")

                # Validate LLM provider if being changed
                if "llm_provider" in body or "llm_model" in body:
                    llm_provider = body.get("llm_provider", current_config.agent.llm_provider)
                    llm_model = body.get("llm_model", current_config.agent.llm_model)

                    # Get the provider config (with any updates from the request)
                    llm_provider_config = current_config.providers.get_provider_config(llm_provider)

                    # Apply any updates from the request
                    api_key = getattr(llm_provider_config, "api_key", None)
                    endpoint = getattr(llm_provider_config, "endpoint", None)
                    project_id = getattr(llm_provider_config, "project_id", None)

                    if f"{llm_provider}_api_key" in body and body[f"{llm_provider}_api_key"].strip():
                        api_key = body[f"{llm_provider}_api_key"]
                    if f"{llm_provider}_endpoint" in body:
                        endpoint = body[f"{llm_provider}_endpoint"]
                    if f"{llm_provider}_project_id" in body:
                        project_id = body[f"{llm_provider}_project_id"]

                    await validate_provider_setup(
                        provider=llm_provider,
                        api_key=api_key,
                        llm_model=llm_model,
                        endpoint=endpoint,
                        project_id=project_id,
                    )
                    logger.info(f"LLM provider validation successful for {llm_provider}")

                # Validate embedding provider if being changed
                if "embedding_provider" in body or "embedding_model" in body:
                    embedding_provider = body.get("embedding_provider", current_config.knowledge.embedding_provider)
                    embedding_model = body.get("embedding_model", current_config.knowledge.embedding_model)

                    # Get the provider config (with any updates from the request)
                    embedding_provider_config = current_config.providers.get_provider_config(embedding_provider)

                    # Apply any updates from the request
                    api_key = getattr(embedding_provider_config, "api_key", None)
                    endpoint = getattr(embedding_provider_config, "endpoint", None)
                    project_id = getattr(embedding_provider_config, "project_id", None)

                    if f"{embedding_provider}_api_key" in body and body[f"{embedding_provider}_api_key"].strip():
                        api_key = body[f"{embedding_provider}_api_key"]
                    if f"{embedding_provider}_endpoint" in body:
                        endpoint = body[f"{embedding_provider}_endpoint"]
                    if f"{embedding_provider}_project_id" in body:
                        project_id = body[f"{embedding_provider}_project_id"]

                    await validate_provider_setup(
                        provider=embedding_provider,
                        api_key=api_key,
                        embedding_model=embedding_model,
                        endpoint=endpoint,
                        project_id=project_id,
                    )
                    logger.info(f"Embedding provider validation successful for {embedding_provider}")

            except Exception as e:
                logger.error(f"Provider validation failed: {str(e)}")
                return JSONResponse({"error": f"{str(e)}"}, status_code=400)

        # Update configuration
        # Only reached if validation passed or wasn't needed
        config_updated = False

        # Update agent settings
        if "llm_model" in body:
            old_model = current_config.agent.llm_model
            current_config.agent.llm_model = body["llm_model"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_LLM_MODEL
            )
            logger.info(f"LLM model changed from {old_model} to {body['llm_model']}")

        if "llm_provider" in body:
            old_provider = current_config.agent.llm_provider
            current_config.agent.llm_provider = body["llm_provider"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_LLM_PROVIDER
            )
            logger.info(f"LLM provider changed from {old_provider} to {body['llm_provider']}")

        if "system_prompt" in body:
            current_config.agent.system_prompt = body["system_prompt"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_SYSTEM_PROMPT
            )

            # Also update the chat flow with the new system prompt
            try:
                flows_service = _get_flows_service()
                await _update_langflow_system_prompt(current_config, flows_service)
            except Exception as e:
                logger.error(f"Failed to update chat flow system prompt: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        # Update knowledge settings
        if "embedding_model" in body:
            old_model = current_config.knowledge.embedding_model
            new_embedding_model = body["embedding_model"].strip()
            current_config.knowledge.embedding_model = new_embedding_model
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_EMBED_MODEL
            )
            logger.info(f"Embedding model changed from {old_model} to {new_embedding_model}")

        if "embedding_provider" in body:
            old_provider = current_config.knowledge.embedding_provider
            current_config.knowledge.embedding_provider = body["embedding_provider"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_EMBED_PROVIDER
            )
            logger.info(f"Embedding provider changed from {old_provider} to {body['embedding_provider']}")

        if "table_structure" in body:
            current_config.knowledge.table_structure = body["table_structure"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_DOCLING_UPDATED
            )

            # Also update the flow with the new docling settings
            try:
                flows_service = _get_flows_service()
                await _update_langflow_docling_settings(current_config, flows_service)
            except Exception as e:
                logger.error(f"Failed to update docling settings in flow: {str(e)}")

        if "ocr" in body:
            current_config.knowledge.ocr = body["ocr"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_DOCLING_UPDATED
            )

            # Also update the flow with the new docling settings
            try:
                flows_service = _get_flows_service()
                await _update_langflow_docling_settings(current_config, flows_service)
            except Exception as e:
                logger.error(f"Failed to update docling settings in flow: {str(e)}")

        if "picture_descriptions" in body:
            current_config.knowledge.picture_descriptions = body["picture_descriptions"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_DOCLING_UPDATED
            )

            # Also update the flow with the new docling settings
            try:
                flows_service = _get_flows_service()
                await _update_langflow_docling_settings(current_config, flows_service)
            except Exception as e:
                logger.error(f"Failed to update docling settings in flow: {str(e)}")

        if "chunk_size" in body:
            current_config.knowledge.chunk_size = body["chunk_size"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_CHUNK_UPDATED
            )

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
            current_config.knowledge.chunk_overlap = body["chunk_overlap"]
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_CHUNK_UPDATED
            )

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

        # Update provider-specific settings
        provider_updated = False
        if "openai_api_key" in body and body["openai_api_key"].strip():
            current_config.providers.openai.api_key = body["openai_api_key"].strip()
            current_config.providers.openai.configured = True
            config_updated = True
            provider_updated = True

        if "anthropic_api_key" in body and body["anthropic_api_key"].strip():
            current_config.providers.anthropic.api_key = body["anthropic_api_key"]
            current_config.providers.anthropic.configured = True
            config_updated = True
            provider_updated = True

        if "watsonx_api_key" in body and body["watsonx_api_key"].strip():
            current_config.providers.watsonx.api_key = body["watsonx_api_key"]
            current_config.providers.watsonx.configured = True
            config_updated = True
            provider_updated = True

        if "watsonx_endpoint" in body:
            current_config.providers.watsonx.endpoint = body["watsonx_endpoint"].strip()
            current_config.providers.watsonx.configured = True
            config_updated = True
            provider_updated = True

        if "watsonx_project_id" in body:
            current_config.providers.watsonx.project_id = body["watsonx_project_id"].strip()
            current_config.providers.watsonx.configured = True
            config_updated = True
            provider_updated = True

        if "ollama_endpoint" in body:
            current_config.providers.ollama.endpoint = body["ollama_endpoint"].strip()
            current_config.providers.ollama.configured = True
            config_updated = True
            provider_updated = True
        
        if provider_updated:
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS, 
                MessageId.ORB_SETTINGS_PROVIDER_CREDS
            )

        if not config_updated:
            return JSONResponse(
                {"error": "No valid fields provided for update"}, status_code=400
            )

        # Save the updated configuration
        if not config_manager.save_config_file(current_config):
            return JSONResponse(
                {"error": "Failed to save configuration"}, status_code=500
            )

        # Update Langflow global variables and model values if provider settings changed
        provider_fields_to_check = [
            "llm_provider", "embedding_provider",
            "openai_api_key", "anthropic_api_key",
            "watsonx_api_key", "watsonx_endpoint", "watsonx_project_id",
            "ollama_endpoint"
        ]

        await clients.refresh_patched_client()

        if any(key in body for key in provider_fields_to_check):
            try:
                flows_service = _get_flows_service()
                
                # Update global variables
                await _update_langflow_global_variables(current_config)

                # Update LLM client credentials when embedding selection changes
                if "embedding_provider" in body or "embedding_model" in body:
                    await _update_mcp_servers_with_provider_credentials(
                        current_config, session_manager
                    )
                
                # Update model values if provider or model changed
                if "llm_provider" in body or "llm_model" in body or "embedding_provider" in body or "embedding_model" in body:
                    await _update_langflow_model_values(current_config, flows_service)

            except Exception as e:
                logger.error(f"Failed to update Langflow settings: {str(e)}")
                # Don't fail the entire settings update if Langflow update fails
                # The config was still saved


        logger.info(
            "Configuration updated successfully", updated_fields=list(body.keys())
        )
        await TelemetryClient.send_event(
            Category.SETTINGS_OPERATIONS, 
            MessageId.ORB_SETTINGS_UPDATED
        )
        return JSONResponse({"message": "Configuration updated successfully"})

    except Exception as e:
        logger.error("Failed to update settings", error=str(e))
        await TelemetryClient.send_event(
            Category.SETTINGS_OPERATIONS, 
            MessageId.ORB_SETTINGS_UPDATE_FAILED
        )
        return JSONResponse(
            {"error": f"Failed to update settings: {str(e)}"}, status_code=500
        )


async def onboarding(request, flows_service, session_manager=None):
    """Handle onboarding configuration setup"""
    try:
        await TelemetryClient.send_event(Category.ONBOARDING, MessageId.ORB_ONBOARD_START)
        
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
            "llm_provider",
            "llm_model",
            "embedding_provider",
            "embedding_model",
            "sample_data",
            # Provider-specific fields
            "openai_api_key",
            "anthropic_api_key",
            "watsonx_api_key",
            "watsonx_endpoint",
            "watsonx_project_id",
            "ollama_endpoint",
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

        # Update agent settings (LLM)
        llm_model_selected = None
        llm_provider_selected = None
        
        if "llm_model" in body:
            if not isinstance(body["llm_model"], str) or not body["llm_model"].strip():
                return JSONResponse(
                    {"error": "llm_model must be a non-empty string"}, status_code=400
                )
            llm_model_selected = body["llm_model"].strip()
            current_config.agent.llm_model = llm_model_selected
            config_updated = True
            await TelemetryClient.send_event(
                Category.ONBOARDING, 
                MessageId.ORB_ONBOARD_LLM_MODEL,
                metadata={"llm_model": llm_model_selected}
            )
            logger.info(f"LLM model selected during onboarding: {llm_model_selected}")

        if "llm_provider" in body:
            if (
                not isinstance(body["llm_provider"], str)
                or not body["llm_provider"].strip()
            ):
                return JSONResponse(
                    {"error": "llm_provider must be a non-empty string"},
                    status_code=400,
                )
            if body["llm_provider"] not in ["openai", "anthropic", "watsonx", "ollama"]:
                return JSONResponse(
                    {"error": "llm_provider must be one of: openai, anthropic, watsonx, ollama"},
                    status_code=400,
                )
            llm_provider_selected = body["llm_provider"].strip()
            current_config.agent.llm_provider = llm_provider_selected
            config_updated = True
            await TelemetryClient.send_event(
                Category.ONBOARDING, 
                MessageId.ORB_ONBOARD_LLM_PROVIDER,
                metadata={"llm_provider": llm_provider_selected}
            )
            logger.info(f"LLM provider selected during onboarding: {llm_provider_selected}")

        # Update knowledge settings (embedding)
        embedding_model_selected = None
        embedding_provider_selected = None
        
        if "embedding_model" in body and not DISABLE_INGEST_WITH_LANGFLOW:
            if (
                not isinstance(body["embedding_model"], str)
                or not body["embedding_model"].strip()
            ):
                return JSONResponse(
                    {"error": "embedding_model must be a non-empty string"},
                    status_code=400,
                )
            embedding_model_selected = body["embedding_model"].strip()
            current_config.knowledge.embedding_model = embedding_model_selected
            config_updated = True
            await TelemetryClient.send_event(
                Category.ONBOARDING, 
                MessageId.ORB_ONBOARD_EMBED_MODEL,
                metadata={"embedding_model": embedding_model_selected}
            )
            logger.info(f"Embedding model selected during onboarding: {embedding_model_selected}")

        if "embedding_provider" in body:
            if (
                not isinstance(body["embedding_provider"], str)
                or not body["embedding_provider"].strip()
            ):
                return JSONResponse(
                    {"error": "embedding_provider must be a non-empty string"},
                    status_code=400,
                )
            # Anthropic doesn't have embeddings
            if body["embedding_provider"] not in ["openai", "watsonx", "ollama"]:
                return JSONResponse(
                    {"error": "embedding_provider must be one of: openai, watsonx, ollama"},
                    status_code=400,
                )
            embedding_provider_selected = body["embedding_provider"].strip()
            current_config.knowledge.embedding_provider = embedding_provider_selected
            config_updated = True
            await TelemetryClient.send_event(
                Category.ONBOARDING, 
                MessageId.ORB_ONBOARD_EMBED_PROVIDER,
                metadata={"embedding_provider": embedding_provider_selected}
            )
            logger.info(f"Embedding provider selected during onboarding: {embedding_provider_selected}")

        # Update provider-specific credentials
        if "openai_api_key" in body and body["openai_api_key"].strip():
            current_config.providers.openai.api_key = body["openai_api_key"].strip()
            current_config.providers.openai.configured = True
            config_updated = True

        if "anthropic_api_key" in body and body["anthropic_api_key"].strip():
            current_config.providers.anthropic.api_key = body["anthropic_api_key"]
            current_config.providers.anthropic.configured = True
            config_updated = True

        if "watsonx_api_key" in body and body["watsonx_api_key"].strip():
            current_config.providers.watsonx.api_key = body["watsonx_api_key"]
            current_config.providers.watsonx.configured = True
            config_updated = True

        if "watsonx_endpoint" in body:
            if not isinstance(body["watsonx_endpoint"], str) or not body["watsonx_endpoint"].strip():
                return JSONResponse(
                    {"error": "watsonx_endpoint must be a non-empty string"}, status_code=400
                )
            current_config.providers.watsonx.endpoint = body["watsonx_endpoint"].strip()
            current_config.providers.watsonx.configured = True
            config_updated = True

        if "watsonx_project_id" in body:
            if (
                not isinstance(body["watsonx_project_id"], str)
                or not body["watsonx_project_id"].strip()
            ):
                return JSONResponse(
                    {"error": "watsonx_project_id must be a non-empty string"}, status_code=400
                )
            current_config.providers.watsonx.project_id = body["watsonx_project_id"].strip()
            current_config.providers.watsonx.configured = True
            config_updated = True

        if "ollama_endpoint" in body:
            if not isinstance(body["ollama_endpoint"], str) or not body["ollama_endpoint"].strip():
                return JSONResponse(
                    {"error": "ollama_endpoint must be a non-empty string"}, status_code=400
                )
            current_config.providers.ollama.endpoint = body["ollama_endpoint"].strip()
            current_config.providers.ollama.configured = True
            config_updated = True

        # Mark providers as configured if they were chosen during onboarding
        # Check LLM provider
        if "llm_provider" in body:
            llm_provider = body["llm_provider"].strip().lower()
            if llm_provider == "openai" and current_config.providers.openai.api_key:
                current_config.providers.openai.configured = True
                logger.info("Marked OpenAI as configured (chosen as LLM provider)")
            elif llm_provider == "anthropic" and current_config.providers.anthropic.api_key:
                current_config.providers.anthropic.configured = True
                logger.info("Marked Anthropic as configured (chosen as LLM provider)")
            elif llm_provider == "watsonx" and current_config.providers.watsonx.api_key and current_config.providers.watsonx.endpoint and current_config.providers.watsonx.project_id:
                current_config.providers.watsonx.configured = True
                logger.info("Marked WatsonX as configured (chosen as LLM provider)")
            elif llm_provider == "ollama" and current_config.providers.ollama.endpoint:
                current_config.providers.ollama.configured = True
                logger.info("Marked Ollama as configured (chosen as LLM provider)")

        # Check embedding provider
        if "embedding_provider" in body:
            embedding_provider = body["embedding_provider"].strip().lower()
            if embedding_provider == "openai" and current_config.providers.openai.api_key:
                current_config.providers.openai.configured = True
                logger.info("Marked OpenAI as configured (chosen as embedding provider)")
            elif embedding_provider == "watsonx" and current_config.providers.watsonx.api_key and current_config.providers.watsonx.endpoint and current_config.providers.watsonx.project_id:
                current_config.providers.watsonx.configured = True
                logger.info("Marked WatsonX as configured (chosen as embedding provider)")
            elif embedding_provider == "ollama" and current_config.providers.ollama.endpoint:
                current_config.providers.ollama.configured = True
                logger.info("Marked Ollama as configured (chosen as embedding provider)")

        # Handle sample_data
        should_ingest_sample_data = False
        if "sample_data" in body:
            if not isinstance(body["sample_data"], bool):
                return JSONResponse(
                    {"error": "sample_data must be a boolean value"}, status_code=400
                )
            should_ingest_sample_data = body["sample_data"]
            if should_ingest_sample_data:
                await TelemetryClient.send_event(
                    Category.ONBOARDING, 
                    MessageId.ORB_ONBOARD_SAMPLE_DATA
                )
                logger.info("Sample data ingestion requested during onboarding")

        if not config_updated:
            return JSONResponse(
                {"error": "No valid fields provided for update"}, status_code=400
            )

        # Validate provider setup before initializing OpenSearch index
        try:
            from api.provider_validation import validate_provider_setup

            # Validate LLM provider if set
            if "llm_provider" in body or "llm_model" in body:
                llm_provider = current_config.agent.llm_provider.lower()
                llm_provider_config = current_config.get_llm_provider_config()

                logger.info(f"Validating LLM provider setup for {llm_provider}")
                await validate_provider_setup(
                    provider=llm_provider,
                    api_key=getattr(llm_provider_config, "api_key", None),
                    llm_model=current_config.agent.llm_model,
                    endpoint=getattr(llm_provider_config, "endpoint", None),
                    project_id=getattr(llm_provider_config, "project_id", None),
                )
                logger.info(f"LLM provider setup validation completed successfully for {llm_provider}")

            # Validate embedding provider if set
            if "embedding_provider" in body or "embedding_model" in body:
                embedding_provider = current_config.knowledge.embedding_provider.lower()
                embedding_provider_config = current_config.get_embedding_provider_config()

                logger.info(f"Validating embedding provider setup for {embedding_provider}")
                await validate_provider_setup(
                    provider=embedding_provider,
                    api_key=getattr(embedding_provider_config, "api_key", None),
                    embedding_model=current_config.knowledge.embedding_model,
                    endpoint=getattr(embedding_provider_config, "endpoint", None),
                    project_id=getattr(embedding_provider_config, "project_id", None),
                )
                logger.info(f"Embedding provider setup validation completed successfully for {embedding_provider}")
        except Exception as e:
            logger.error(f"Provider validation failed: {str(e)}")
            return JSONResponse(
                {"error": str(e)},
                status_code=400,
            )

        # Set Langflow global variables and model values based on provider configuration
        try:
            # Check if any provider-related fields were provided
            provider_fields_provided = any(key in body for key in [
                "openai_api_key", "anthropic_api_key",
                "watsonx_api_key", "watsonx_endpoint", "watsonx_project_id",
                "ollama_endpoint"
            ])
            
            # Update global variables if any provider fields were provided
            # or if existing config has values (for OpenAI/Anthropic that might already be set)
            if (provider_fields_provided or 
                current_config.providers.openai.api_key != "" or 
                current_config.providers.anthropic.api_key != ""):
                await _update_langflow_global_variables(current_config)
            
            if "embedding_provider" in body or "embedding_model" in body:
                await _update_mcp_servers_with_provider_credentials(current_config, session_manager)

            # Update model values if provider or model fields were provided
            if "llm_provider" in body or "llm_model" in body or "embedding_provider" in body or "embedding_model" in body:
                await _update_langflow_model_values(current_config, flows_service)

        except Exception as e:
            logger.error(
                "Failed to set Langflow global variables and model values",
                error=str(e),
            )
            raise

        # Initialize the OpenSearch index if embedding model is configured
        if "embedding_model" in body or "embedding_provider" in body:
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
            
            # Mark config as edited and send telemetry with model information
            current_config.edited = True
            
            # Build metadata with selected models
            onboarding_metadata = {}
            if llm_provider_selected:
                onboarding_metadata["llm_provider"] = llm_provider_selected
            if llm_model_selected:
                onboarding_metadata["llm_model"] = llm_model_selected
            if embedding_provider_selected:
                onboarding_metadata["embedding_provider"] = embedding_provider_selected
            if embedding_model_selected:
                onboarding_metadata["embedding_model"] = embedding_model_selected
            
            await TelemetryClient.send_event(
                Category.ONBOARDING, 
                MessageId.ORB_ONBOARD_CONFIG_EDITED,
                metadata=onboarding_metadata
            )
            await TelemetryClient.send_event(
                Category.ONBOARDING, 
                MessageId.ORB_ONBOARD_COMPLETE,
                metadata=onboarding_metadata
            )
            logger.info("Configuration marked as edited after onboarding")

        else:
            await TelemetryClient.send_event(
                Category.ONBOARDING, 
                MessageId.ORB_ONBOARD_FAILED
            )
            return JSONResponse(
                {"error": "Failed to save configuration"}, status_code=500
            )

        # Refresh cached patched client so latest credentials take effect immediately
        await clients.refresh_patched_client()

        # Create OpenRAG Docs knowledge filter if sample data was ingested
        # Only create on embedding step to avoid duplicates (both LLM and embedding cards submit with sample_data)
        openrag_docs_filter_id = None
        if should_ingest_sample_data and ("embedding_provider" in body or "embedding_model" in body):
            try:
                openrag_docs_filter_id = await _create_openrag_docs_filter(
                    request, session_manager
                )
                if openrag_docs_filter_id:
                    logger.info(
                        "Created OpenRAG Docs knowledge filter",
                        filter_id=openrag_docs_filter_id,
                    )
            except Exception as e:
                logger.error(
                    "Failed to create OpenRAG Docs knowledge filter", error=str(e)
                )
                # Don't fail onboarding if filter creation fails

        return JSONResponse(
            {
                "message": "Onboarding configuration updated successfully",
                "edited": True,  # Confirm that config is now marked as edited
                "sample_data_ingested": should_ingest_sample_data,
                "openrag_docs_filter_id": openrag_docs_filter_id,
            }
        )

    except Exception as e:
        logger.error("Failed to update onboarding settings", error=str(e))
        await TelemetryClient.send_event(
            Category.ONBOARDING, 
            MessageId.ORB_ONBOARD_FAILED
        )
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


async def _create_openrag_docs_filter(request, session_manager):
    """Create the OpenRAG Docs knowledge filter for onboarding"""
    import uuid
    import json
    from datetime import datetime

    # Get knowledge filter service from app state
    app = request.scope.get("app")
    if not app or not hasattr(app.state, "services"):
        logger.error("Could not access services for knowledge filter creation")
        return None

    knowledge_filter_service = app.state.services.get("knowledge_filter_service")
    if not knowledge_filter_service:
        logger.error("Knowledge filter service not available")
        return None

    # Get user and JWT token from request
    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    # In no-auth mode, set owner to None so filter is visible to all users
    # In auth mode, use the actual user as owner
    if is_no_auth_mode():
        owner_user_id = None
    else:
        owner_user_id = user.user_id

    # Create the filter document
    filter_id = str(uuid.uuid4())
    query_data = json.dumps({
        "query": "",
        "filters": {
            "data_sources": ["openrag-documentation.pdf"],
            "document_types": ["*"],
            "owners": ["*"],
            "connector_types": ["*"],
        },
        "limit": 10,
        "scoreThreshold": 0,
        "color": "blue",
        "icon": "book",
    })

    filter_doc = {
        "id": filter_id,
        "name": "OpenRAG Docs",
        "description": "Filter for OpenRAG documentation",
        "query_data": query_data,
        "owner": owner_user_id,
        "allowed_users": [],
        "allowed_groups": [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    result = await knowledge_filter_service.create_knowledge_filter(
        filter_doc, user_id=user.user_id, jwt_token=jwt_token
    )

    if result.get("success"):
        return filter_id
    else:
        logger.error("Failed to create OpenRAG Docs filter", error=result.get("error"))
        return None


def _get_flows_service():
    """Helper function to get flows service instance"""
    from services.flows_service import FlowsService

    return FlowsService()


async def _update_langflow_global_variables(config):
    """Update Langflow global variables for all configured providers"""
    try:
        # WatsonX global variables
        if config.providers.watsonx.api_key:
            await clients._create_langflow_global_variable(
                "WATSONX_API_KEY", config.providers.watsonx.api_key, modify=True
            )
            logger.info("Set WATSONX_API_KEY global variable in Langflow")

        if config.providers.watsonx.project_id:
            await clients._create_langflow_global_variable(
                "WATSONX_PROJECT_ID", config.providers.watsonx.project_id, modify=True
            )
            logger.info("Set WATSONX_PROJECT_ID global variable in Langflow")

        # OpenAI global variables
        if config.providers.openai.api_key:
            await clients._create_langflow_global_variable(
                "OPENAI_API_KEY", config.providers.openai.api_key, modify=True
            )
            logger.info("Set OPENAI_API_KEY global variable in Langflow")

        # Anthropic global variables
        if config.providers.anthropic.api_key:
            await clients._create_langflow_global_variable(
                "ANTHROPIC_API_KEY", config.providers.anthropic.api_key, modify=True
            )
            logger.info("Set ANTHROPIC_API_KEY global variable in Langflow")

        # Ollama global variables
        if config.providers.ollama.endpoint:
            endpoint = transform_localhost_url(config.providers.ollama.endpoint)
            await clients._create_langflow_global_variable(
                "OLLAMA_BASE_URL", endpoint, modify=True
            )
            logger.info("Set OLLAMA_BASE_URL global variable in Langflow")

        if config.knowledge.embedding_model:
            await clients._create_langflow_global_variable(
                "SELECTED_EMBEDDING_MODEL", config.knowledge.embedding_model, modify=True
            )
            logger.info(
                f"Set SELECTED_EMBEDDING_MODEL global variable to {config.knowledge.embedding_model}"
            )

    except Exception as e:
        logger.error(f"Failed to update Langflow global variables: {str(e)}")
        raise


async def _update_mcp_servers_with_provider_credentials(config, session_manager = None):
    # Update MCP servers with provider credentials
    try:
        from services.langflow_mcp_service import LangflowMCPService
        from utils.langflow_headers import build_mcp_global_vars_from_config
        
        mcp_service = LangflowMCPService()
        
        # Build global vars using utility function
        mcp_global_vars = build_mcp_global_vars_from_config(config)
        
        # In no-auth mode, add the anonymous JWT token and user details
        if is_no_auth_mode() and session_manager:
            from session_manager import AnonymousUser
            
            # Create/get anonymous JWT for no-auth mode
            anonymous_jwt = session_manager.get_effective_jwt_token(None, None)
            if anonymous_jwt:
                mcp_global_vars["JWT"] = anonymous_jwt
            
            # Add anonymous user details
            anonymous_user = AnonymousUser()
            mcp_global_vars["OWNER"] = anonymous_user.user_id  # "anonymous"
            mcp_global_vars["OWNER_NAME"] = f'"{anonymous_user.name}"'  # "Anonymous User" (quoted)
            mcp_global_vars["OWNER_EMAIL"] = anonymous_user.email  # "anonymous@localhost"
            
            logger.debug("Added anonymous JWT and user details to MCP servers for no-auth mode")
        
        if mcp_global_vars:
            result = await mcp_service.update_mcp_servers_with_global_vars(mcp_global_vars)
            logger.info("Updated MCP servers with provider credentials after settings change", **result)
        
    except Exception as mcp_error:
        logger.warning(f"Failed to update MCP servers after settings change: {str(mcp_error)}")
        # Don't fail the entire settings update if MCP update fails


async def _update_langflow_model_values(config, flows_service):
    """Update model values across Langflow flows"""
    try:
        # Update LLM model values
        llm_provider = config.agent.llm_provider.lower()
        llm_provider_config = config.get_llm_provider_config()
        llm_endpoint = getattr(llm_provider_config, "endpoint", None)

        await flows_service.change_langflow_model_value(
            llm_provider,
            llm_model=config.agent.llm_model,
            endpoint=llm_endpoint,
        )
        logger.info(
            f"Successfully updated Langflow flows for LLM provider {llm_provider}"
        )

        # Update embedding model values
        embedding_provider = config.knowledge.embedding_provider.lower()
        embedding_provider_config = config.get_embedding_provider_config()
        embedding_endpoint = getattr(embedding_provider_config, "endpoint", None)

        await flows_service.change_langflow_model_value(
            embedding_provider,
            embedding_model=config.knowledge.embedding_model,
            endpoint=embedding_endpoint,
        )
        logger.info(
            f"Successfully updated Langflow flows for embedding provider {embedding_provider}"
        )

    except Exception as e:
        logger.error(f"Failed to update Langflow model values: {str(e)}")
        raise


async def _update_langflow_system_prompt(config, flows_service):
    """Update system prompt in chat flow"""
    try:
        llm_provider = config.agent.llm_provider.lower()
        await flows_service.update_chat_flow_system_prompt(
            config.agent.system_prompt, llm_provider
        )
        logger.info("Successfully updated chat flow system prompt")
    except Exception as e:
        logger.error(f"Failed to update chat flow system prompt: {str(e)}")
        raise


async def _update_langflow_docling_settings(config, flows_service):
    """Update docling settings in ingest flow"""
    try:
        preset_config = get_docling_preset_configs(
            table_structure=config.knowledge.table_structure,
            ocr=config.knowledge.ocr,
            picture_descriptions=config.knowledge.picture_descriptions,
        )
        await flows_service.update_flow_docling_preset("custom", preset_config)
        logger.info("Successfully updated docling settings in ingest flow")
    except Exception as e:
        logger.error(f"Failed to update docling settings: {str(e)}")
        raise


async def _update_langflow_chunk_settings(config, flows_service):
    """Update chunk size and overlap in ingest flow"""
    try:
        await flows_service.update_ingest_flow_chunk_size(config.knowledge.chunk_size)
        logger.info(f"Successfully updated ingest flow chunk size to {config.knowledge.chunk_size}")

        await flows_service.update_ingest_flow_chunk_overlap(config.knowledge.chunk_overlap)
        logger.info(f"Successfully updated ingest flow chunk overlap to {config.knowledge.chunk_overlap}")
    except Exception as e:
        logger.error(f"Failed to update chunk settings: {str(e)}")
        raise


async def reapply_all_settings(session_manager = None):
    """
    Reapply all current configuration settings to Langflow flows and global variables.
    This is called when flows are detected to have been reset.
    """
    try:
        config = get_openrag_config()
        flows_service = _get_flows_service()

        logger.info("Reapplying all settings to Langflow flows and global variables")

        if config.knowledge.embedding_model or config.knowledge.embedding_provider:
            await _update_mcp_servers_with_provider_credentials(config, session_manager)
        else:
            logger.info("No embedding model or provider configured, skipping MCP server update")

        # Update all Langflow settings using helper functions
        try:
            await _update_langflow_global_variables(config)
        except Exception as e:
            logger.error(f"Failed to update Langflow global variables: {str(e)}")
            # Continue with other updates even if global variables fail

        try:
            await _update_langflow_model_values(config, flows_service)
        except Exception as e:
            logger.error(f"Failed to update Langflow model values: {str(e)}")

        try:
            await _update_langflow_system_prompt(config, flows_service)
        except Exception as e:
            logger.error(f"Failed to update Langflow system prompt: {str(e)}")

        try:
            await _update_langflow_docling_settings(config, flows_service)
        except Exception as e:
            logger.error(f"Failed to update Langflow docling settings: {str(e)}")

        try:
            await _update_langflow_chunk_settings(config, flows_service)
        except Exception as e:
            logger.error(f"Failed to update Langflow chunk settings: {str(e)}")

        logger.info("Successfully reapplied all settings to Langflow flows")

    except Exception as e:
        logger.error(f"Failed to reapply settings: {str(e)}")
        raise


async def update_docling_preset(request, session_manager):
    """Update docling settings in the ingest flow - deprecated endpoint, use /settings instead"""
    try:
        # Parse request body
        body = await request.json()

        # Support old preset-based API for backwards compatibility
        if "preset" in body:
            # Map old presets to new toggle settings
            preset_map = {
                "standard": {
                    "table_structure": False,
                    "ocr": False,
                    "picture_descriptions": False,
                },
                "ocr": {
                    "table_structure": False,
                    "ocr": True,
                    "picture_descriptions": False,
                },
                "picture_description": {
                    "table_structure": False,
                    "ocr": True,
                    "picture_descriptions": True,
                },
                "VLM": {
                    "table_structure": False,
                    "ocr": False,
                    "picture_descriptions": False,
                },
            }

            preset = body["preset"]
            if preset not in preset_map:
                return JSONResponse(
                    {
                        "error": f"Invalid preset '{preset}'. Valid presets: {', '.join(preset_map.keys())}"
                    },
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

        logger.info("Successfully updated docling settings in ingest flow")

        return JSONResponse(
            {
                "message": "Successfully updated docling settings",
                "settings": settings,
                "preset_config": preset_config,
            }
        )

    except Exception as e:
        logger.error("Failed to update docling settings", error=str(e))
        return JSONResponse(
            {"error": f"Failed to update docling settings: {str(e)}"}, status_code=500
        )
