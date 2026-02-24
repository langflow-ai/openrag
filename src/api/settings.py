import json
import platform
from fastapi import Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger
from utils.telemetry import TelemetryClient, Category, MessageId
from config.settings import (
    DISABLE_INGEST_WITH_LANGFLOW,
    INGEST_SAMPLE_DATA,
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
from typing import List, Optional, Any, Dict

from api.provider_validation import validate_provider_setup
from utils.langflow_utils import LangflowNotReadyError, wait_for_langflow
from dependencies import (
    get_session_manager,
    get_flows_service,
    get_task_service,
    get_current_user,
    get_document_service,
    get_langflow_file_service,
    get_knowledge_filter_service,
)
from session_manager import User

logger = get_logger(__name__)


class SettingsUpdateBody(BaseModel):
    llm_model: Optional[str] = Field(None, min_length=1)
    llm_provider: Optional[str] = Field(None, pattern="^(openai|anthropic|watsonx|ollama)$")
    system_prompt: Optional[str] = None
    chunk_size: Optional[int] = Field(None, gt=0)
    chunk_overlap: Optional[int] = Field(None, ge=0)
    table_structure: Optional[bool] = None
    ocr: Optional[bool] = None
    picture_descriptions: Optional[bool] = None
    embedding_model: Optional[str] = Field(None, min_length=1)
    embedding_provider: Optional[str] = Field(None, pattern="^(openai|watsonx|ollama)$")
    index_name: Optional[str] = Field(None, min_length=1)
    openai_api_key: Optional[str] = Field(None, min_length=1)
    anthropic_api_key: Optional[str] = Field(None, min_length=1)
    watsonx_api_key: Optional[str] = Field(None, min_length=1)
    watsonx_endpoint: Optional[str] = Field(None, min_length=1)
    watsonx_project_id: Optional[str] = Field(None, min_length=1)
    ollama_endpoint: Optional[str] = Field(None, min_length=1)


class OnboardingBody(BaseModel):
    llm_provider: Optional[str] = Field(None, pattern="^(openai|anthropic|watsonx|ollama)$")
    llm_model: Optional[str] = Field(None, min_length=1)
    embedding_provider: Optional[str] = Field(None, pattern="^(openai|watsonx|ollama)$")
    embedding_model: Optional[str] = Field(None, min_length=1)
    openai_api_key: Optional[str] = Field(None, min_length=1)
    anthropic_api_key: Optional[str] = Field(None, min_length=1)
    watsonx_api_key: Optional[str] = Field(None, min_length=1)
    watsonx_endpoint: Optional[str] = Field(None, min_length=1)
    watsonx_project_id: Optional[str] = Field(None, min_length=1)
    ollama_endpoint: Optional[str] = Field(None, min_length=1)


class AssistantMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class OnboardingStateBody(BaseModel):
    current_step: Optional[int] = None
    assistant_message: Optional[AssistantMessage] = None
    selected_nudge: Optional[str] = None
    card_steps: Optional[Dict[str, Any]] = None
    upload_steps: Optional[Dict[str, Any]] = None
    openrag_docs_filter_id: Optional[str] = None
    user_doc_filter_id: Optional[str] = None


class DoclingPresetBody(BaseModel):
    preset: Optional[str] = None
    table_structure: Optional[bool] = None
    ocr: Optional[bool] = None
    picture_descriptions: Optional[bool] = None


class OnboardingStateConfig(BaseModel):
    current_step: Optional[int]
    assistant_message: Optional[AssistantMessage]
    selected_nudge: Optional[str]
    card_steps: Optional[Dict[str, Any]]
    upload_steps: Optional[Dict[str, Any]]
    openrag_docs_filter_id: Optional[str]
    user_doc_filter_id: Optional[str]

class OpenAIProviderConfig(BaseModel):
    has_api_key: bool
    configured: bool

class AnthropicProviderConfig(BaseModel):
    has_api_key: bool
    configured: bool

class WatsonXProviderConfig(BaseModel):
    has_api_key: bool
    endpoint: Optional[str]
    project_id: Optional[str]
    configured: bool

class OllamaProviderConfig(BaseModel):
    endpoint: Optional[str]
    configured: bool

class ProvidersConfig(BaseModel):
    openai: OpenAIProviderConfig
    anthropic: AnthropicProviderConfig
    watsonx: WatsonXProviderConfig
    ollama: OllamaProviderConfig

class KnowledgeConfig(BaseModel):
    embedding_model: Optional[str]
    embedding_provider: Optional[str]
    chunk_size: Optional[int]
    chunk_overlap: Optional[int]
    table_structure: Optional[bool]
    ocr: Optional[bool]
    picture_descriptions: Optional[bool]
    index_name: Optional[str]

class AgentConfig(BaseModel):
    llm_model: Optional[str]
    llm_provider: Optional[str]
    system_prompt: Optional[str]

class IngestionDefaultsConfig(BaseModel):
    chunkSize: Optional[int]
    chunkOverlap: Optional[int]
    separator: Optional[str]
    embeddingModel: Optional[str]

class SettingsResponse(BaseModel):
    langflow_url: str
    flow_id: Optional[str]
    ingest_flow_id: Optional[str]
    langflow_public_url: Optional[str]
    edited: bool
    onboarding: OnboardingStateConfig
    providers: ProvidersConfig
    knowledge: KnowledgeConfig
    agent: AgentConfig
    localhost_url: str
    langflow_edit_url: Optional[str] = None
    langflow_ingest_edit_url: Optional[str] = None
    ingestion_defaults: Optional[IngestionDefaultsConfig] = None


class OnboardingResponse(BaseModel):
    message: str
    edited: bool
    sample_data_ingested: bool
    openrag_docs_filter_id: Optional[str] = None

class DoclingConfig(BaseModel):
    do_ocr: bool
    ocr_engine: str
    do_table_structure: bool
    do_picture_classification: bool
    do_picture_description: bool
    picture_description_local: Optional[dict] = None

class DoclingPresetResponse(BaseModel):
    message: str
    settings: dict
    preset_config: DoclingConfig

class OnboardingStateResponse(BaseModel):
    message: str
    updated_fields: List[str]

class SettingsUpdateResponse(BaseModel):
    message: str

class RollbackResponse(BaseModel):
    message: str
    cancelled_tasks: int
    deleted_files: int


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


async def get_settings(
    request: Request,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
) -> SettingsResponse:
    """Get application settings"""
    try:
        openrag_config = get_openrag_config()

        knowledge_config = openrag_config.knowledge
        agent_config = openrag_config.agent

        # Only expose edit URLs when a public URL is configured
        langflow_edit_url = None
        if LANGFLOW_PUBLIC_URL and LANGFLOW_CHAT_FLOW_ID:
            langflow_edit_url = f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_CHAT_FLOW_ID}"

        langflow_ingest_edit_url = None
        if LANGFLOW_PUBLIC_URL and LANGFLOW_INGEST_FLOW_ID:
            langflow_ingest_edit_url = f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_INGEST_FLOW_ID}"

        ingestion_defaults_obj = None
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

                    ingestion_defaults_obj = IngestionDefaultsConfig(**ingestion_defaults)

            except Exception as e:
                logger.warning(f"Failed to fetch ingestion flow defaults: {e}")
                # Continue without ingestion defaults

        return SettingsResponse(
            langflow_url=LANGFLOW_URL,
            flow_id=LANGFLOW_CHAT_FLOW_ID,
            ingest_flow_id=LANGFLOW_INGEST_FLOW_ID,
            langflow_public_url=LANGFLOW_PUBLIC_URL,
            edited=openrag_config.edited,
            onboarding=OnboardingStateConfig(
                current_step=openrag_config.onboarding.current_step,
                assistant_message=openrag_config.onboarding.assistant_message,
                selected_nudge=openrag_config.onboarding.selected_nudge,
                card_steps=openrag_config.onboarding.card_steps,
                upload_steps=openrag_config.onboarding.upload_steps,
                openrag_docs_filter_id=openrag_config.onboarding.openrag_docs_filter_id,
                user_doc_filter_id=openrag_config.onboarding.user_doc_filter_id,
            ),
            providers=ProvidersConfig(
                openai=OpenAIProviderConfig(
                    has_api_key=bool(openrag_config.providers.openai.api_key),
                    configured=openrag_config.providers.openai.configured,
                ),
                anthropic=AnthropicProviderConfig(
                    has_api_key=bool(openrag_config.providers.anthropic.api_key),
                    configured=openrag_config.providers.anthropic.configured,
                ),
                watsonx=WatsonXProviderConfig(
                    has_api_key=bool(openrag_config.providers.watsonx.api_key),
                    endpoint=openrag_config.providers.watsonx.endpoint or None,
                    project_id=openrag_config.providers.watsonx.project_id or None,
                    configured=openrag_config.providers.watsonx.configured,
                ),
                ollama=OllamaProviderConfig(
                    endpoint=openrag_config.providers.ollama.endpoint or None,
                    configured=openrag_config.providers.ollama.configured,
                ),
            ),
            knowledge=KnowledgeConfig(
                embedding_model=knowledge_config.embedding_model,
                embedding_provider=knowledge_config.embedding_provider,
                chunk_size=knowledge_config.chunk_size,
                chunk_overlap=knowledge_config.chunk_overlap,
                table_structure=knowledge_config.table_structure,
                ocr=knowledge_config.ocr,
                picture_descriptions=knowledge_config.picture_descriptions,
                index_name=knowledge_config.index_name,
            ),
            agent=AgentConfig(
                llm_model=agent_config.llm_model,
                llm_provider=agent_config.llm_provider,
                system_prompt=agent_config.system_prompt,
            ),
            localhost_url=LOCALHOST_URL,
            langflow_edit_url=langflow_edit_url,
            langflow_ingest_edit_url=langflow_ingest_edit_url,
            ingestion_defaults=ingestion_defaults_obj,
        )

    except Exception as e:
        logger.error(f"Failed to retrieve settings: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to retrieve settings: {str(e)}"}, status_code=500
        )


async def update_settings(
    body: SettingsUpdateBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
) -> SettingsUpdateResponse:
    """Update settings in configuration"""
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
        
        should_validate = any(getattr(body, field) is not None for field in provider_fields)

        if should_validate:
            try:
                logger.info("Running provider validation before modifying config")

                # Validate LLM provider if being changed
                if body.llm_provider is not None or body.llm_model is not None:
                    llm_provider = body.llm_provider if body.llm_provider is not None else current_config.agent.llm_provider
                    llm_model = body.llm_model if body.llm_model is not None else current_config.agent.llm_model

                    # Get the provider config (with any updates from the request)
                    llm_provider_config = current_config.providers.get_provider_config(llm_provider)

                    # Apply any updates from the request
                    api_key = getattr(llm_provider_config, "api_key", None)
                    endpoint = getattr(llm_provider_config, "endpoint", None)
                    project_id = getattr(llm_provider_config, "project_id", None)

                    if getattr(body, f"{llm_provider}_api_key") is not None and getattr(body, f"{llm_provider}_api_key").strip():
                        api_key = getattr(body, f"{llm_provider}_api_key")
                    if getattr(body, f"{llm_provider}_endpoint") is not None:
                        endpoint = getattr(body, f"{llm_provider}_endpoint")
                    if getattr(body, f"{llm_provider}_project_id") is not None:
                        project_id = getattr(body, f"{llm_provider}_project_id")

                    await validate_provider_setup(
                        provider=llm_provider,
                        api_key=api_key,
                        llm_model=llm_model,
                        endpoint=endpoint,
                        project_id=project_id,
                    )
                    logger.info(f"LLM provider validation successful for {llm_provider}")

                # Validate embedding provider if being changed
                if body.embedding_provider is not None or body.embedding_model is not None:
                    embedding_provider = body.embedding_provider if body.embedding_provider is not None else current_config.knowledge.embedding_provider
                    embedding_model = body.embedding_model if body.embedding_model is not None else current_config.knowledge.embedding_model

                    # Get the provider config (with any updates from the request)
                    embedding_provider_config = current_config.providers.get_provider_config(embedding_provider)

                    # Apply any updates from the request
                    api_key = getattr(embedding_provider_config, "api_key", None)
                    endpoint = getattr(embedding_provider_config, "endpoint", None)
                    project_id = getattr(embedding_provider_config, "project_id", None)

                    if getattr(body, f"{embedding_provider}_api_key") is not None and getattr(body, f"{embedding_provider}_api_key").strip():
                        api_key = getattr(body, f"{embedding_provider}_api_key")
                    if getattr(body, f"{embedding_provider}_endpoint") is not None:
                        endpoint = getattr(body, f"{embedding_provider}_endpoint")
                    if getattr(body, f"{embedding_provider}_project_id") is not None:
                        project_id = getattr(body, f"{embedding_provider}_project_id")

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
        if body.llm_model is not None:
            old_model = current_config.agent.llm_model
            current_config.agent.llm_model = body.llm_model
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS,
                MessageId.ORB_SETTINGS_LLM_MODEL
            )
            logger.info(f"LLM model changed from {old_model} to {body.llm_model}")

        if body.llm_provider is not None:
            old_provider = current_config.agent.llm_provider
            current_config.agent.llm_provider = body.llm_provider
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS,
                MessageId.ORB_SETTINGS_LLM_PROVIDER
            )
            logger.info(f"LLM provider changed from {old_provider} to {body.llm_provider}")

        if body.system_prompt is not None:
            current_config.agent.system_prompt = body.system_prompt
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
        if body.embedding_model is not None:
            old_model = current_config.knowledge.embedding_model
            new_embedding_model = body.embedding_model.strip()
            current_config.knowledge.embedding_model = new_embedding_model
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS,
                MessageId.ORB_SETTINGS_EMBED_MODEL
            )
            logger.info(f"Embedding model changed from {old_model} to {new_embedding_model}")

        if body.embedding_provider is not None:
            old_provider = current_config.knowledge.embedding_provider
            current_config.knowledge.embedding_provider = body.embedding_provider
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS,
                MessageId.ORB_SETTINGS_EMBED_PROVIDER
            )
            logger.info(f"Embedding provider changed from {old_provider} to {body.embedding_provider}")

        if body.table_structure is not None:
            current_config.knowledge.table_structure = body.table_structure
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

        if body.ocr is not None:
            current_config.knowledge.ocr = body.ocr
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

        if body.picture_descriptions is not None:
            current_config.knowledge.picture_descriptions = body.picture_descriptions
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

        if body.chunk_size is not None:
            current_config.knowledge.chunk_size = body.chunk_size
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS,
                MessageId.ORB_SETTINGS_CHUNK_UPDATED
            )

            # Also update the ingest flow with the new chunk size
            try:
                flows_service = _get_flows_service()
                await flows_service.update_ingest_flow_chunk_size(body.chunk_size)
                logger.info(
                    f"Successfully updated ingest flow chunk size to {body.chunk_size}"
                )
            except Exception as e:
                logger.error(f"Failed to update ingest flow chunk size: {str(e)}")
                # Don't fail the entire settings update if flow update fails
                # The config will still be saved

        if body.chunk_overlap is not None:
            current_config.knowledge.chunk_overlap = body.chunk_overlap
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS,
                MessageId.ORB_SETTINGS_CHUNK_UPDATED
            )

            # Also update the ingest flow with the new chunk overlap
            try:
                flows_service = _get_flows_service()
                await flows_service.update_ingest_flow_chunk_overlap(
                    body.chunk_overlap
                )
                logger.info(
                    f"Successfully updated ingest flow chunk overlap to {body.chunk_overlap}"
                )
            except Exception as e:
                logger.error(f"Failed to update ingest flow chunk overlap: {str(e)}")
                # Don't fail the entire settings update if flow update fails
        if body.index_name is not None:
            old_index_name = current_config.knowledge.index_name
            new_index_name = body.index_name.strip()
            current_config.knowledge.index_name = new_index_name
            config_updated = True
            await TelemetryClient.send_event(
                Category.SETTINGS_OPERATIONS,
                MessageId.ORB_SETTINGS_INDEX_NAME_UPDATED
            )
            logger.info(f"Index name changed from {old_index_name} to {new_index_name}")

            # Also update global variable with new index name
            try:
                await clients._create_langflow_global_variable("OPENSEARCH_INDEX_NAME", new_index_name, modify=True)
                logger.info(
                    f"Successfully updated global variable with new index name {new_index_name}"
                )
            except Exception as e:
                logger.error(f"Failed to update global variable with new index name: {str(e)}")
                # Don't fail the entire settings update if flow update fails

                # The config will still be saved

        # Update provider-specific settings
        provider_updated = False
        if body.openai_api_key is not None and body.openai_api_key.strip():
            current_config.providers.openai.api_key = body.openai_api_key.strip()
            current_config.providers.openai.configured = True
            config_updated = True
            provider_updated = True

        if body.anthropic_api_key is not None and body.anthropic_api_key.strip():
            current_config.providers.anthropic.api_key = body.anthropic_api_key
            current_config.providers.anthropic.configured = True
            config_updated = True
            provider_updated = True

        if body.watsonx_api_key is not None and body.watsonx_api_key.strip():
            current_config.providers.watsonx.api_key = body.watsonx_api_key
            current_config.providers.watsonx.configured = True
            config_updated = True
            provider_updated = True

        if body.watsonx_endpoint is not None:
            current_config.providers.watsonx.endpoint = body.watsonx_endpoint.strip()
            current_config.providers.watsonx.configured = True
            config_updated = True
            provider_updated = True

        if body.watsonx_project_id is not None:
            current_config.providers.watsonx.project_id = body.watsonx_project_id.strip()
            current_config.providers.watsonx.configured = True
            config_updated = True
            provider_updated = True

        if body.ollama_endpoint is not None:
            current_config.providers.ollama.endpoint = body.ollama_endpoint.strip()
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
        await clients.refresh_patched_client()

        if should_validate:
            try:
                flows_service = _get_flows_service()

                # Update global variables
                await _update_langflow_global_variables(current_config)

                # Update LLM client credentials when embedding selection changes
                if body.embedding_provider is not None or body.embedding_model is not None:
                    await _update_mcp_servers_with_provider_credentials(
                        current_config, session_manager
                    )

                # Update model values if provider or model changed
                if body.llm_provider is not None or body.llm_model is not None or body.embedding_provider is not None or body.embedding_model is not None:
                    await _update_langflow_model_values(current_config, flows_service)

            except Exception as e:
                logger.error(f"Failed to update Langflow settings: {str(e)}")
                # Don't fail the entire settings update if Langflow update fails
                # The config was still saved


        set_fields = [k for k, v in body.model_dump().items() if v is not None]
        logger.info(
            "Configuration updated successfully", updated_fields=set_fields
        )
        await TelemetryClient.send_event(
            Category.SETTINGS_OPERATIONS,
            MessageId.ORB_SETTINGS_UPDATED
        )
        return SettingsUpdateResponse(message="Configuration updated successfully")

    except Exception as e:
        logger.error("Failed to update settings", error=str(e))
        await TelemetryClient.send_event(
            Category.SETTINGS_OPERATIONS,
            MessageId.ORB_SETTINGS_UPDATE_FAILED
        )
        return JSONResponse(
            {"error": f"Failed to update settings: {str(e)}"}, status_code=500
        )


async def onboarding(
    body: OnboardingBody,
    flows_service=Depends(get_flows_service),
    session_manager=Depends(get_session_manager),
    document_service=Depends(get_document_service),
    task_service=Depends(get_task_service),
    langflow_file_service=Depends(get_langflow_file_service),
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    user: User = Depends(get_current_user),
) -> OnboardingResponse:
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

        # Update configuration
        config_updated = False

        # Update agent settings (LLM)
        llm_model_selected = None
        llm_provider_selected = None

        if body.llm_model:
            llm_model_selected = body.llm_model.strip()
            current_config.agent.llm_model = llm_model_selected
            config_updated = True
            await TelemetryClient.send_event(
                Category.ONBOARDING,
                MessageId.ORB_ONBOARD_LLM_MODEL,
                metadata={"llm_model": llm_model_selected}
            )
            logger.info(f"LLM model selected during onboarding: {llm_model_selected}")

        if body.llm_provider:
            llm_provider_selected = body.llm_provider.strip()
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

        if body.embedding_model and not DISABLE_INGEST_WITH_LANGFLOW:
            embedding_model_selected = body.embedding_model.strip()
            current_config.knowledge.embedding_model = embedding_model_selected
            config_updated = True
            await TelemetryClient.send_event(
                Category.ONBOARDING,
                MessageId.ORB_ONBOARD_EMBED_MODEL,
                metadata={"embedding_model": embedding_model_selected}
            )
            logger.info(f"Embedding model selected during onboarding: {embedding_model_selected}")

        if body.embedding_provider:
            embedding_provider_selected = body.embedding_provider.strip()
            current_config.knowledge.embedding_provider = embedding_provider_selected
            config_updated = True
            await TelemetryClient.send_event(
                Category.ONBOARDING,
                MessageId.ORB_ONBOARD_EMBED_PROVIDER,
                metadata={"embedding_provider": embedding_provider_selected}
            )
            logger.info(f"Embedding provider selected during onboarding: {embedding_provider_selected}")

        # Update provider-specific credentials
        if body.openai_api_key:
            current_config.providers.openai.api_key = body.openai_api_key.strip()
            current_config.providers.openai.configured = True
            config_updated = True

        if body.anthropic_api_key:
            current_config.providers.anthropic.api_key = body.anthropic_api_key.strip()
            current_config.providers.anthropic.configured = True
            config_updated = True

        if body.watsonx_api_key:
            current_config.providers.watsonx.api_key = body.watsonx_api_key.strip()
            current_config.providers.watsonx.configured = True
            config_updated = True

        if body.watsonx_endpoint:
            current_config.providers.watsonx.endpoint = body.watsonx_endpoint.strip()
            current_config.providers.watsonx.configured = True
            config_updated = True

        if body.watsonx_project_id:
            current_config.providers.watsonx.project_id = body.watsonx_project_id.strip()
            current_config.providers.watsonx.configured = True
            config_updated = True

        if body.ollama_endpoint:
            current_config.providers.ollama.endpoint = body.ollama_endpoint.strip()
            current_config.providers.ollama.configured = True
            config_updated = True

        # Mark providers as configured if they were chosen during onboarding
        # Check LLM provider
        if body.llm_provider:
            llm_provider = body.llm_provider.strip().lower()
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
        if body.embedding_provider:
            embedding_provider = body.embedding_provider.strip().lower()
            if embedding_provider == "openai" and current_config.providers.openai.api_key:
                current_config.providers.openai.configured = True
                logger.info("Marked OpenAI as configured (chosen as embedding provider)")
            elif embedding_provider == "watsonx" and current_config.providers.watsonx.api_key and current_config.providers.watsonx.endpoint and current_config.providers.watsonx.project_id:
                current_config.providers.watsonx.configured = True
                logger.info("Marked WatsonX as configured (chosen as embedding provider)")
            elif embedding_provider == "ollama" and current_config.providers.ollama.endpoint:
                current_config.providers.ollama.configured = True
                logger.info("Marked Ollama as configured (chosen as embedding provider)")

        should_ingest_sample_data = INGEST_SAMPLE_DATA
        if should_ingest_sample_data:
            await TelemetryClient.send_event(
                Category.ONBOARDING,
                MessageId.ORB_ONBOARD_SAMPLE_DATA
            )
            logger.info("Sample data ingestion enabled via environment variable")

        if not config_updated:
            return JSONResponse(
                {"error": "No valid fields provided for update"}, status_code=400
            )

        # Validate provider setup before initializing OpenSearch index
        # Use full validation with completion tests (test_completion=True) to ensure provider health during onboarding
        try:
            from api.provider_validation import validate_provider_setup

            # Validate LLM provider if set
            if body.llm_provider or body.llm_model:
                llm_provider = current_config.agent.llm_provider.lower()
                llm_provider_config = current_config.get_llm_provider_config()

                logger.info(f"Validating LLM provider setup for {llm_provider} (full validation with completion test)")
                await validate_provider_setup(
                    provider=llm_provider,
                    api_key=getattr(llm_provider_config, "api_key", None),
                    llm_model=current_config.agent.llm_model,
                    endpoint=getattr(llm_provider_config, "endpoint", None),
                    project_id=getattr(llm_provider_config, "project_id", None),
                    test_completion=True,  # Full validation with completion test - ensures provider health
                )
                logger.info(f"LLM provider setup validation completed successfully for {llm_provider}")

            # Validate embedding provider if set
            if body.embedding_provider or body.embedding_model:
                embedding_provider = current_config.knowledge.embedding_provider.lower()
                embedding_provider_config = current_config.get_embedding_provider_config()

                logger.info(f"Validating embedding provider setup for {embedding_provider} (full validation with completion test)")
                await validate_provider_setup(
                    provider=embedding_provider,
                    api_key=getattr(embedding_provider_config, "api_key", None),
                    embedding_model=current_config.knowledge.embedding_model,
                    endpoint=getattr(embedding_provider_config, "endpoint", None),
                    project_id=getattr(embedding_provider_config, "project_id", None),
                    test_completion=True,  # Full validation with completion test - ensures provider health
                )
                logger.info(f"Embedding provider setup validation completed successfully for {embedding_provider}")
        except Exception as e:
            logger.error(f"Provider validation failed: {str(e)}")
            return JSONResponse(
                {"error": str(e)},
                status_code=400,
            )

        # Ensure the Langflow service is ready before attempting to configure it
        try:
            await wait_for_langflow()
        except LangflowNotReadyError as e:
            message: str = "Aborted the Langflow service configuration process. The Langflow service is not ready."
            logger.error(message, error=str(e))

            return JSONResponse(
                {
                    "error": message
                },
                status_code=503,
            )

        # Set Langflow global variables and model values based on provider configuration
        try:
            # Check if any provider-related fields were provided
            provider_fields_provided = any([
                body.openai_api_key, body.anthropic_api_key,
                body.watsonx_api_key, body.watsonx_endpoint, body.watsonx_project_id,
                body.ollama_endpoint
            ])

            # Update global variables if any provider fields were provided
            # or if existing config has values (for OpenAI/Anthropic that might already be set)
            if (provider_fields_provided or
                current_config.providers.openai.api_key != "" or
                current_config.providers.anthropic.api_key != ""):
                await _update_langflow_global_variables(current_config)

            if body.embedding_provider or body.embedding_model:
                await _update_mcp_servers_with_provider_credentials(current_config, session_manager)

            # Update model values if provider or model fields were provided
            if body.llm_provider or body.llm_model or body.embedding_provider or body.embedding_model:
                await _update_langflow_model_values(current_config, flows_service)

        except Exception as e:
            logger.error(
                "Failed to set Langflow global variables and model values",
                error=str(e),
            )
            raise

        # Initialize the OpenSearch index if embedding model is configured
        if body.embedding_model or body.embedding_provider:
            try:
                # Import here to avoid circular imports
                from main import init_index_when_ready

                logger.info(
                    "Initializing OpenSearch index after onboarding configuration"
                )
                await init_index_when_ready()
                logger.info("OpenSearch index initialization completed successfully")
            except Exception as e:
                logger.error(
                    "Failed to initialize OpenSearch index after onboarding",
                    error=str(e),
                )
                return JSONResponse(
                    {
                        "error": str(e),
                    },
                    status_code=500,
                )

            # Handle sample data ingestion if requested
            if should_ingest_sample_data:
                try:
                    # Import the function here to avoid circular imports
                    from main import ingest_default_documents_when_ready

                    await ingest_default_documents_when_ready(
                        document_service,
                        task_service,
                        langflow_file_service,
                        session_manager,
                    )
                    logger.info("Sample data ingestion completed successfully")

                except Exception as e:
                    logger.error(
                        "Failed to complete sample data ingestion", error=str(e)
                    )
                    return JSONResponse(
                        {"error": f"Failed to ingest sample documents: {str(e)}"},
                        status_code=500
                    )

        if config_manager.save_config_file(current_config):
            set_fields = [k for k, v in body.model_dump(exclude_unset=True).items()]
            logger.info(
                "Onboarding configuration updated successfully",
                updated_fields=set_fields,
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
        if should_ingest_sample_data and (body.embedding_provider or body.embedding_model):
            try:
                openrag_docs_filter_id = await _create_openrag_docs_filter(
                    knowledge_filter_service, session_manager, user
                )
                if openrag_docs_filter_id:
                    logger.info(
                        "Created OpenRAG Docs knowledge filter",
                        filter_id=openrag_docs_filter_id,
                    )
                    # Save the filter ID to the config
                    current_config.onboarding.openrag_docs_filter_id = openrag_docs_filter_id
                    if not config_manager.save_config_file(current_config):
                        logger.error("Failed to save openrag_docs_filter_id to config")
            except Exception as e:
                logger.error(
                    "Failed to create OpenRAG Docs knowledge filter", error=str(e)
                )
                # Don't fail onboarding if filter creation fails

        return OnboardingResponse(
            message="Onboarding configuration updated successfully",
            edited=True,  # Confirm that config is now marked as edited
            sample_data_ingested=should_ingest_sample_data,
            openrag_docs_filter_id=openrag_docs_filter_id,
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


async def _create_openrag_docs_filter(
    knowledge_filter_service, session_manager, user
):
    """Create the OpenRAG Docs knowledge filter for onboarding"""
    import uuid
    import json
    from datetime import datetime

    if not knowledge_filter_service:
        logger.error("Knowledge filter service not available")
        return None

    # Get JWT token
        jwt_token = user.jwt_token

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


async def update_onboarding_state(
    body: OnboardingStateBody,
    user: User = Depends(get_current_user),
) -> OnboardingStateResponse:
    """Update onboarding state in configuration"""
    try:
        await TelemetryClient.send_event(Category.ONBOARDING, MessageId.ORB_ONBOARD_START)

        # Convert body to dict excluding None values
        body_dict = body.model_dump(exclude_unset=True)

        # Update onboarding state using config manager
        success = config_manager.update_onboarding_state(**body_dict)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update onboarding state")

        logger.info(f"Onboarding state updated: {body}")

        return OnboardingStateResponse(
            message="Onboarding state updated successfully",
            updated_fields=list(body_dict.keys()),
        )

    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON in request body"}, status_code=400
        )
    except Exception as e:
        logger.error(f"Error updating onboarding state: {str(e)}")
        return JSONResponse(
            {"error": f"Failed to update onboarding state: {str(e)}"},
            status_code=500,
        )


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


async def rollback_onboarding(
    request: Request,
    session_manager=Depends(get_session_manager),
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
) -> RollbackResponse:
    """Rollback onboarding configuration when sample data files fail.

    This will:
    1. Cancel all active tasks
    2. Delete successfully ingested knowledge documents
    3. Reset configuration to allow re-onboarding
    """
    try:
        # Get current configuration
        current_config = get_openrag_config()

        # Only allow rollback if config was marked as edited (onboarding completed)
        if not current_config.edited:
            return JSONResponse(
                {"error": "No onboarding configuration to rollback"}, status_code=400
            )

            jwt_token = user.jwt_token

        logger.info("Rolling back onboarding configuration due to file failures")

        # Get all tasks for the user
        all_tasks = task_service.get_all_tasks(user.user_id)

        cancelled_tasks = []
        deleted_files = []

        # Cancel all active tasks and collect successfully ingested files
        for task_data in all_tasks:
            task_id = task_data.get("task_id")
            task_status = task_data.get("status")

            # Cancel active tasks (pending, running, processing)
            if task_status in ["pending", "running", "processing"]:
                try:
                    success = await task_service.cancel_task(user.user_id, task_id)
                    if success:
                        cancelled_tasks.append(task_id)
                        logger.info(f"Cancelled task {task_id}")
                except Exception as e:
                    logger.error(f"Failed to cancel task {task_id}: {str(e)}")

            # For completed tasks, find successfully ingested files and delete them
            elif task_status == "completed":
                files = task_data.get("files", {})
                if isinstance(files, dict):
                    for file_path, file_info in files.items():
                        # Check if file was successfully ingested
                        if isinstance(file_info, dict):
                            file_status = file_info.get("status")
                            filename = file_info.get("filename") or file_path.split("/")[-1]

                            if file_status == "completed" and filename:
                                try:
                                    # Get user's OpenSearch client
                                    opensearch_client = session_manager.get_user_opensearch_client(
                                        user.user_id, jwt_token
                                    )

                                    # Delete documents by filename
                                    from utils.opensearch_queries import build_filename_delete_body
                                    from config.settings import get_index_name

                                    delete_query = build_filename_delete_body(filename)

                                    result = await opensearch_client.delete_by_query(
                                        index=get_index_name(),
                                        body=delete_query,
                                        conflicts="proceed"
                                    )

                                    deleted_count = result.get("deleted", 0)
                                    if deleted_count > 0:
                                        deleted_files.append(filename)
                                        logger.info(f"Deleted {deleted_count} chunks for filename {filename}")
                                except Exception as e:
                                    logger.error(f"Failed to delete documents for {filename}: {str(e)}")

        # Clear embedding provider and model settings
        current_config.knowledge.embedding_provider = "openai"  # Reset to default
        current_config.knowledge.embedding_model = ""

        # Mark config as not edited so user can go through onboarding again
        current_config.edited = False

        # Save the rolled back configuration manually to avoid save_config_file setting edited=True
        try:
            import yaml
            config_file = config_manager.config_file

            # Ensure directory exists
            config_file.parent.mkdir(parents=True, exist_ok=True)

            # Save config with edited=False
            with open(config_file, "w") as f:
                yaml.dump(current_config.to_dict(), f, default_flow_style=False, indent=2)

            # Update cached config
            config_manager._config = current_config

            logger.info("Successfully saved rolled back configuration with edited=False")
        except Exception as e:
            logger.error(f"Failed to save rolled back configuration: {e}")
            return JSONResponse(
                {"error": "Failed to save rolled back configuration"}, status_code=500
            )

        logger.info(
            f"Successfully rolled back onboarding configuration. "
            f"Cancelled {len(cancelled_tasks)} tasks, deleted {len(deleted_files)} files"
        )
        await TelemetryClient.send_event(
            Category.ONBOARDING,
            MessageId.ORB_ONBOARD_ROLLBACK
        )

        return RollbackResponse(
            message="Onboarding configuration rolled back successfully",
            cancelled_tasks=len(cancelled_tasks),
            deleted_files=len(deleted_files),
        )

    except Exception as e:
        logger.error("Failed to rollback onboarding configuration", error=str(e))
        return JSONResponse(
            {"error": f"Failed to rollback onboarding: {str(e)}"}, status_code=500
        )


async def update_docling_preset(
    body: DoclingPresetBody,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
) -> DoclingPresetResponse:
    """Update docling settings in the ingest flow - deprecated endpoint, use /settings instead"""
    try:
        # Support old preset-based API for backwards compatibility
        if body.preset:
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

            preset = body.preset
            if preset not in preset_map:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid preset '{preset}'. Valid presets: {', '.join(preset_map.keys())}"
                )

            settings_toggles = preset_map[preset]
        else:
            # Support new toggle-based API
            settings_toggles = {
                "table_structure": body.table_structure if body.table_structure is not None else False,
                "ocr": body.ocr if body.ocr is not None else False,
                "picture_descriptions": body.picture_descriptions if body.picture_descriptions is not None else False,
            }

        # Get the preset configuration
        preset_config_dict = get_docling_preset_configs(**settings_toggles)
        preset_config = DoclingConfig(**preset_config_dict)

        # Use the helper function to update the flow
        flows_service = _get_flows_service()
        await flows_service.update_flow_docling_preset("custom", preset_config_dict)

        logger.info("Successfully updated docling settings in ingest flow")

        return DoclingPresetResponse(
            message="Successfully updated docling settings",
            settings=settings_toggles,
            preset_config=preset_config,
        )

    except Exception as e:
        logger.error("Failed to update docling settings", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to update docling settings: {str(e)}")
