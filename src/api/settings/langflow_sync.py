"""Langflow synchronization helpers for settings/onboarding flows.

Pushes the latest user config (provider creds, model selection, system
prompt, docling toggles, chunk sizes, MCP server URLs) into Langflow
flows and global variables. Also exposes `reapply_all_settings`, called
from `services/startup_orchestrator.py` when flow-reset detection
triggers a full re-sync.

Lifted verbatim from the original `src/api/settings.py` (lines 46,
1458–1684, 1725–1770). No behavior change.
"""

import asyncio
import os

from api.settings.helpers import (
    _EMBEDDING_PROVIDER_NAMES,
    _LLM_PROVIDER_NAMES,
    _configured_provider_names,
    _get_flows_service,
)
from config.settings import clients, get_openrag_config
from services.docling_service import get_docling_preset_configs
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Strong refs to in-flight async post-save sync tasks so they aren't
# garbage-collected mid-flight when the originating request returns.
_background_tasks: set[asyncio.Task] = set()

LANGFLOW_CREDENTIAL_GLOBAL_VARIABLES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "JWT",
        "OPENAI_API_KEY",
        "OPENSEARCH_PASSWORD",
        "WATSONX_APIKEY",
    }
)

LANGFLOW_GENERIC_GLOBAL_VARIABLES = frozenset(
    {
        "DOCLING_SERVE_URL",
        "DOCLING_SERVE_VERIFY_SSL",
        "DOCLING_TASK_ID",
        "FILESIZE",
        "MIMETYPE",
        "OLLAMA_BASE_URL",
        "OPENRAG-QUERY-FILTER",
        "OPENRAG_INGEST_BATCH_SIZE",
        "OPENRAG_INGEST_RUN_ID",
        "OPENRAG_INGEST_TOKEN",
        "OPENRAG_INGEST_URL",
        "OPENSEARCH_INDEX_NAME",
        "OPENSEARCH_URL",
        "SELECTED_EMBEDDING_MODEL",
        "SELECTED_EMBEDDING_MODEL_PROVIDER",
        "SELECTED_LANGUAGE_MODEL",
        "SELECTED_LANGUAGE_MODEL_PROVIDER",
        "WATSONX_PROJECT_ID",
        "WATSONX_URL",
    }
)


def _langflow_global_variable_type(name: str) -> str:
    if name in LANGFLOW_GENERIC_GLOBAL_VARIABLES:
        return "Generic"
    return "Credential"


async def _upsert_langflow_global_variable(name: str, value: str, modify: bool = True):
    await clients._create_langflow_global_variable(
        name,
        value,
        modify=modify,
        variable_type=_langflow_global_variable_type(name),
    )


def _string_value(value) -> str:
    return "" if value is None else str(value)


def _env_or_config(name: str, config_value, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        value = config_value
    if value is None or value == "":
        value = default
    return str(value)


def _first_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _required_generic_global_values(config) -> dict[str, str]:
    knowledge = getattr(config, "knowledge", None)
    providers = getattr(config, "providers", None)
    watsonx = getattr(providers, "watsonx", None)
    ollama = getattr(providers, "ollama", None)

    return {
        "DOCLING_SERVE_URL": os.getenv("DOCLING_SERVE_URL", "http://host.docker.internal:5001"),
        "DOCLING_SERVE_VERIFY_SSL": os.getenv("DOCLING_SERVE_VERIFY_SSL", "true"),
        "DOCLING_TASK_ID": os.getenv("DOCLING_TASK_ID", "None"),
        "FILESIZE": os.getenv("FILESIZE", "0"),
        "MIMETYPE": os.getenv("MIMETYPE", "None"),
        "OLLAMA_BASE_URL": _string_value(
            _first_env_value("OLLAMA_BASE_URL", "OLLAMA_ENDPOINT")
            or getattr(ollama, "endpoint", None)
        ),
        "OPENRAG-QUERY-FILTER": os.getenv("OPENRAG-QUERY-FILTER", "{}"),
        "OPENRAG_INGEST_BATCH_SIZE": os.getenv("OPENRAG_INGEST_BATCH_SIZE", "100"),
        "OPENRAG_INGEST_RUN_ID": os.getenv("OPENRAG_INGEST_RUN_ID", "OPENRAG_INGEST_RUN_ID"),
        "OPENRAG_INGEST_TOKEN": os.getenv("OPENRAG_INGEST_TOKEN", "OPENRAG_INGEST_TOKEN"),
        "OPENRAG_INGEST_URL": os.getenv("OPENRAG_INGEST_URL", "OPENRAG_INGEST_URL"),
        "OPENSEARCH_INDEX_NAME": _env_or_config(
            "OPENSEARCH_INDEX_NAME", getattr(knowledge, "index_name", None), "documents"
        ),
        "OPENSEARCH_URL": os.getenv(
            "OPENSEARCH_URL",
            f"https://{os.getenv('OPENSEARCH_HOST', 'opensearch')}:"
            f"{os.getenv('OPENSEARCH_INTERNAL_PORT', '9200')}",
        ),
        "SELECTED_EMBEDDING_MODEL": _env_or_config(
            "SELECTED_EMBEDDING_MODEL",
            getattr(knowledge, "embedding_model", None),
            "text-embedding-3-small",
        ),
        "SELECTED_EMBEDDING_MODEL_PROVIDER": _env_or_config(
            "SELECTED_EMBEDDING_MODEL_PROVIDER",
            getattr(knowledge, "embedding_provider", None),
            "openai",
        ),
        "SELECTED_LANGUAGE_MODEL": _env_or_config(
            "SELECTED_LANGUAGE_MODEL",
            getattr(getattr(config, "agent", None), "llm_model", None),
            "gpt-4o-mini",
        ),
        "SELECTED_LANGUAGE_MODEL_PROVIDER": _env_or_config(
            "SELECTED_LANGUAGE_MODEL_PROVIDER",
            getattr(getattr(config, "agent", None), "llm_provider", None),
            "openai",
        ),
        "WATSONX_PROJECT_ID": _env_or_config(
            "WATSONX_PROJECT_ID", getattr(watsonx, "project_id", None), ""
        ),
        "WATSONX_URL": _string_value(
            _first_env_value("WATSONX_URL", "WATSONX_ENDPOINT")
            or getattr(watsonx, "endpoint", None)
        ),
    }


async def ensure_required_langflow_global_variables(config=None):
    """Ensure load_from_db plain-string globals are Generic for backwards compatibility."""
    config = config or get_openrag_config()
    required_values = _required_generic_global_values(config)

    for name in sorted(LANGFLOW_GENERIC_GLOBAL_VARIABLES):
        await _upsert_langflow_global_variable(name, _string_value(required_values.get(name, "")))


async def _update_langflow_global_variables(config, flows_service=None):
    """Update Langflow global variables for all configured providers"""
    try:
        # WatsonX global variables
        if config.providers.watsonx.api_key:
            await _upsert_langflow_global_variable("WATSONX_APIKEY", config.providers.watsonx.api_key)
            logger.info("Set WATSONX_APIKEY global variable in Langflow")

        if config.providers.watsonx.project_id:
            await _upsert_langflow_global_variable(
                "WATSONX_PROJECT_ID", config.providers.watsonx.project_id
            )
            logger.info("Set WATSONX_PROJECT_ID global variable in Langflow")

        if config.providers.watsonx.endpoint:
            await _upsert_langflow_global_variable("WATSONX_URL", config.providers.watsonx.endpoint)
            logger.info("Set WATSONX_URL global variable in Langflow")

        # OpenAI global variables
        if config.providers.openai.api_key:
            await _upsert_langflow_global_variable("OPENAI_API_KEY", config.providers.openai.api_key)
            logger.info("Set OPENAI_API_KEY global variable in Langflow")

        # Anthropic global variables
        if config.providers.anthropic.api_key:
            await _upsert_langflow_global_variable(
                "ANTHROPIC_API_KEY", config.providers.anthropic.api_key
            )
            logger.info("Set ANTHROPIC_API_KEY global variable in Langflow")

        # Ollama global variables
        if config.providers.ollama.endpoint:
            if not flows_service:
                flows_service = _get_flows_service()

            endpoint = await flows_service.resolve_ollama_url(
                config.providers.ollama.endpoint, force_refresh=True
            )
            await _upsert_langflow_global_variable("OLLAMA_BASE_URL", endpoint)
            logger.info("Set OLLAMA_BASE_URL global variable in Langflow")

        if config.knowledge.embedding_model:
            await _upsert_langflow_global_variable(
                "SELECTED_EMBEDDING_MODEL", config.knowledge.embedding_model
            )
            logger.info(
                f"Set SELECTED_EMBEDDING_MODEL global variable to {config.knowledge.embedding_model}"
            )
        if config.knowledge.embedding_provider:
            await _upsert_langflow_global_variable(
                "SELECTED_EMBEDDING_MODEL_PROVIDER", config.knowledge.embedding_provider
            )
            logger.info(
                f"Set SELECTED_EMBEDDING_MODEL_PROVIDER global variable to {config.knowledge.embedding_provider}"
            )
        if config.agent.llm_model:
            await _upsert_langflow_global_variable(
                "SELECTED_LANGUAGE_MODEL", config.agent.llm_model
            )
            logger.info(
                f"Set SELECTED_LANGUAGE_MODEL global variable to {config.agent.llm_model}"
            )
        if config.agent.llm_provider:
            await _upsert_langflow_global_variable(
                "SELECTED_LANGUAGE_MODEL_PROVIDER", config.agent.llm_provider
            )
            logger.info(
                f"Set SELECTED_LANGUAGE_MODEL_PROVIDER global variable to {config.agent.llm_provider}"
            )
        # Enable models in Langflow
        await _enable_langflow_models(config, flows_service)
        
    except Exception as e:
        logger.error(f"Failed to update Langflow global variables: {str(e)}")
        raise


async def _enable_langflow_models(config, flows_service):
    """Enable the selected models in Langflow's internal registry."""
    try:
        if config.knowledge.embedding_model and config.knowledge.embedding_provider:
            # Need to get the correct provider display name for Langflow
            provider = config.knowledge.embedding_provider
            provider_name = (
                "IBM WatsonX" if provider == "watsonx" else
                "Ollama" if provider == "ollama" else
                "Anthropic" if provider == "anthropic" else
                "OpenAI"
            )
            await flows_service.enable_model_in_langflow(provider_name, config.knowledge.embedding_model)
            
        if config.agent.llm_model and config.agent.llm_provider:
            provider = config.agent.llm_provider
            provider_name = (
                "IBM WatsonX" if provider == "watsonx" else
                "Ollama" if provider == "ollama" else
                "Anthropic" if provider == "anthropic" else
                "OpenAI"
            )
            await flows_service.enable_model_in_langflow(provider_name, config.agent.llm_model)
            
    except Exception as e:
        logger.error(f"Failed to enable Langflow models: {str(e)}")

async def _run_async_post_save_langflow_updates(
    session_manager,
    update_mcp_servers: bool,
    models_service=None,
) -> None:
    """Apply post-save Langflow synchronization asynchronously."""
    try:
        current_config = get_openrag_config()
        flows_service = _get_flows_service()

        # Refresh model registry so get_litellm_model_name(strict=True) sees the
        # updated provider list — force_remove skips _affected_embedding_models which
        # is the usual registry refresh trigger.
        if models_service is not None:
            await models_service.update_model_registry()

        # Update global variables
        await _update_langflow_global_variables(current_config, flows_service=flows_service)

        # Update LLM client credentials when embedding selection changes
        if update_mcp_servers:
            await _update_mcp_server_urls(
                current_config, session_manager, flows_service=flows_service
            )

        logger.info("Completed asynchronous Langflow post-save sync")
    except Exception as e:
        # Do not fail user request if async sync fails; keep parity with existing behavior.
        logger.error(f"Failed to update Langflow settings asynchronously: {str(e)}")


async def _update_mcp_server_urls(config, session_manager=None, flows_service=None):
    """Update MCP server URLs (patch localhost and convert to streamable HTTP)."""
    try:
        from services.langflow_mcp_service import LangflowMCPService

        mcp_service = LangflowMCPService()
        result = await mcp_service.update_all_mcp_server_urls()
        logger.info("Updated MCP server URLs after settings change", **result)

    except Exception as mcp_error:
        logger.warning(f"Failed to update MCP server URLs after settings change: {str(mcp_error)}")
        # Don't fail the entire settings update if MCP update fails



async def _update_langflow_system_prompt(config, flows_service):
    """Update system prompt in chat flow"""
    try:
        await flows_service.update_chat_flow_system_prompt(config.agent.system_prompt)
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
        logger.info(
            f"Successfully updated ingest flow chunk overlap to {config.knowledge.chunk_overlap}"
        )
    except Exception as e:
        logger.error(f"Failed to update chunk settings: {str(e)}")
        raise


async def reapply_all_settings(session_manager=None):
    """
    Reapply all current configuration settings to Langflow flows and global variables.
    This is called when flows are detected to have been reset.
    """
    try:
        config = get_openrag_config()
        flows_service = _get_flows_service()

        logger.info("Reapplying all settings to Langflow flows and global variables")

        # Update MCP server URLs (patch localhost and convert to streamable HTTP)
        await _update_mcp_server_urls(config, session_manager, flows_service=flows_service)

        # Update all Langflow settings using helper functions
        try:
            await _update_langflow_global_variables(config, flows_service=flows_service)
        except Exception as e:
            logger.error(f"Failed to update Langflow global variables: {str(e)}")
            # Continue with other updates even if global variables fail

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
