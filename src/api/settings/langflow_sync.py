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

from api.settings.helpers import (
    _LLM_PROVIDER_NAMES,
    _configured_provider_names,
    _get_flows_service,
)
from config.settings import clients, get_openrag_config
from services.docling_service import get_docling_preset_configs
from services.flows_service import LANGFLOW_MODEL_VALUE_PROVIDERS
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Strong refs to in-flight async post-save sync tasks so they aren't
# garbage-collected mid-flight when the originating request returns.
_background_tasks: set[asyncio.Task] = set()

# Globals the flows read into plain (non-secret) component fields. Langflow
# 1.11 refuses to build a component when a Credential-typed global is bound to
# such a field — it keeps secret values out of component outputs, logs and
# traces — so these must be created as "Generic". Everything not listed here
# defaults to "Credential" (API keys, tokens, passwords).
#
# Symptom when this is wrong:
#   Error building Component Docling Serve: Cannot use a Credential-typed
#   global variable in 'api_url'.
LANGFLOW_GENERIC_GLOBAL_VARIABLES = frozenset(
    {
        "AZURE_AI_FOUNDRY_API_VERSION",
        "AZURE_AI_FOUNDRY_EMBEDDING_DEPLOYMENT_NAME",
        "AZURE_AI_FOUNDRY_ENDPOINT",
        "AZURE_AI_FOUNDRY_LLM_DEPLOYMENT_NAME",
        "DOCLING_SERVE_URL",
        "DOCLING_TASK_ID",
        "FILESIZE",
        "MIMETYPE",
        "OLLAMA_BASE_URL",
        "OPENRAG-QUERY-FILTER",
        "OPENSEARCH_INDEX_NAME",
        "OPENSEARCH_URL",
        "SELECTED_EMBEDDING_MODEL",
        "WATSONX_PROJECT_ID",
        "WATSONX_URL",
    }
)


def _langflow_global_variable_type(name: str) -> str:
    """Generic for plain-field globals, Credential for secrets."""
    return "Generic" if name in LANGFLOW_GENERIC_GLOBAL_VARIABLES else "Credential"


async def _upsert_langflow_global_variable(name: str, value: str, modify: bool = True):
    """Create/update a Langflow global with the right type for its usage."""
    await clients._create_langflow_global_variable(
        name,
        value,
        modify=modify,
        variable_type=_langflow_global_variable_type(name),
    )


def _string_value(value) -> str:
    return "" if value is None else str(value)


def _required_generic_global_values(config) -> dict[str, str]:
    """Values for globals Langflow would otherwise auto-create as Credential."""
    from config import settings

    knowledge = getattr(config, "knowledge", None)
    providers = getattr(config, "providers", None)
    watsonx = getattr(providers, "watsonx", None)
    ollama = getattr(providers, "ollama", None)

    return {
        "DOCLING_SERVE_URL": settings.get_langflow_docling_url(),
        "DOCLING_TASK_ID": "None",
        "FILESIZE": "0",
        "MIMETYPE": "None",
        "OLLAMA_BASE_URL": _string_value(getattr(ollama, "endpoint", None)),
        "OPENRAG-QUERY-FILTER": "{}",
        "OPENSEARCH_INDEX_NAME": _string_value(getattr(knowledge, "index_name", None))
        or "documents",
        "OPENSEARCH_URL": settings.get_langflow_opensearch_url(),
        "SELECTED_EMBEDDING_MODEL": _string_value(getattr(knowledge, "embedding_model", None)),
        "WATSONX_PROJECT_ID": _string_value(getattr(watsonx, "project_id", None)),
        "WATSONX_URL": _string_value(getattr(watsonx, "endpoint", None)),
    }


async def ensure_required_langflow_global_variables(config=None):
    """Re-type plain-string globals to Generic.

    Langflow auto-creates a global for every name in
    LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT, and creates them as
    Credential. Flows bind several of those to non-secret fields
    (DOCLING_SERVE_URL -> Docling's api_url, OPENSEARCH_INDEX_NAME ->
    the vector store's index_name), which Langflow 1.11 then refuses to
    build. Upserting them here migrates the type — the client deletes and
    recreates when the existing type differs, since PATCH cannot change it.

    Only names this deployment can supply a value for are touched; the
    Azure globals are handled by _update_langflow_global_variables when
    the provider is actually configured.
    """
    config = config or get_openrag_config()
    values = _required_generic_global_values(config)

    for name in sorted(values):
        try:
            await _upsert_langflow_global_variable(name, values[name])
        except Exception as e:
            logger.warning(
                "Failed to ensure Generic type for Langflow global variable",
                variable_name=name,
                error=str(e),
            )


async def _update_langflow_global_variables(config, flows_service=None):
    """Update Langflow global variables for all configured providers"""
    try:
        # WatsonX global variables
        if config.providers.watsonx.api_key:
            await _upsert_langflow_global_variable(
                "WATSONX_APIKEY", config.providers.watsonx.api_key, modify=True
            )
            logger.info("Set WATSONX_APIKEY global variable in Langflow")

        if config.providers.watsonx.project_id:
            await _upsert_langflow_global_variable(
                "WATSONX_PROJECT_ID", config.providers.watsonx.project_id, modify=True
            )
            logger.info("Set WATSONX_PROJECT_ID global variable in Langflow")

        if config.providers.watsonx.endpoint:
            await _upsert_langflow_global_variable(
                "WATSONX_URL", config.providers.watsonx.endpoint, modify=True
            )
            logger.info("Set WATSONX_URL global variable in Langflow")

        # OpenAI global variables
        if config.providers.openai.api_key:
            await _upsert_langflow_global_variable(
                "OPENAI_API_KEY", config.providers.openai.api_key, modify=True
            )
            logger.info("Set OPENAI_API_KEY global variable in Langflow")

        # Anthropic global variables
        if config.providers.anthropic.api_key:
            await _upsert_langflow_global_variable(
                "ANTHROPIC_API_KEY", config.providers.anthropic.api_key, modify=True
            )
            logger.info("Set ANTHROPIC_API_KEY global variable in Langflow")

        # Ollama global variables
        if config.providers.ollama.endpoint:
            if not flows_service:
                flows_service = _get_flows_service()

            endpoint = await flows_service.resolve_ollama_url(
                config.providers.ollama.endpoint, force_refresh=True
            )
            await _upsert_langflow_global_variable("OLLAMA_BASE_URL", endpoint, modify=True)
            logger.info("Set OLLAMA_BASE_URL global variable in Langflow")

        # Azure AI Foundry global variables — names match Langflow's native
        # "Azure AI Foundry" provider metadata (AZURE_AI_FOUNDRY_API_KEY /
        # AZURE_AI_FOUNDRY_ENDPOINT), not LiteLLM's azure_ai/ env var
        # convention used elsewhere for OpenRAG's own direct LiteLLM calls.
        if config.providers.azure_ai_foundry.api_key:
            await _upsert_langflow_global_variable(
                "AZURE_AI_FOUNDRY_API_KEY", config.providers.azure_ai_foundry.api_key, modify=True
            )
            logger.info("Set AZURE_AI_FOUNDRY_API_KEY global variable in Langflow")

        if config.providers.azure_ai_foundry.endpoint:
            await _upsert_langflow_global_variable(
                "AZURE_AI_FOUNDRY_ENDPOINT",
                config.providers.azure_ai_foundry.endpoint,
                modify=True,
            )
            logger.info("Set AZURE_AI_FOUNDRY_ENDPOINT global variable in Langflow")

        # Consumed by the Dockerfile.langflow patch on
        # instantiation.py's get_llm()/_compose_embedding_kwargs() Azure AI
        # Foundry branches — Langflow's own lfx package never threads
        # api-version through for this provider otherwise (see
        # _build_azure_ai_foundry_url in provider_validation.py for the
        # equivalent fix on OpenRAG's own direct calls). Always synced (not
        # gated on the user having set one) — the API Version field is
        # optional in Settings, and Azure's model inference API rejects
        # requests with no api-version at all, so Langflow needs the same
        # default OpenRAG's own calls already fall back to.
        if config.providers.azure_ai_foundry.endpoint:
            from api.provider_validation import AZURE_AI_FOUNDRY_DEFAULT_API_VERSION

            await _upsert_langflow_global_variable(
                "AZURE_AI_FOUNDRY_API_VERSION",
                config.providers.azure_ai_foundry.api_version
                or AZURE_AI_FOUNDRY_DEFAULT_API_VERSION,
                modify=True,
            )
            logger.info("Set AZURE_AI_FOUNDRY_API_VERSION global variable in Langflow")

        if config.providers.azure_ai_foundry.llm_deployment_name or (
            config.agent.llm_provider == "azure_ai_foundry" and config.agent.llm_model
        ):
            llm_dep = (
                config.providers.azure_ai_foundry.llm_deployment_name or config.agent.llm_model
            )
            await _upsert_langflow_global_variable(
                "AZURE_AI_FOUNDRY_LLM_DEPLOYMENT_NAME", llm_dep, modify=True
            )
            logger.info("Set AZURE_AI_FOUNDRY_LLM_DEPLOYMENT_NAME global variable in Langflow")

        if config.providers.azure_ai_foundry.embedding_deployment_name or (
            config.knowledge.embedding_provider == "azure_ai_foundry"
            and config.knowledge.embedding_model
        ):
            embed_dep = (
                config.providers.azure_ai_foundry.embedding_deployment_name
                or config.knowledge.embedding_model
            )
            await _upsert_langflow_global_variable(
                "AZURE_AI_FOUNDRY_EMBEDDING_DEPLOYMENT_NAME", embed_dep, modify=True
            )
            logger.info(
                "Set AZURE_AI_FOUNDRY_EMBEDDING_DEPLOYMENT_NAME global variable in Langflow"
            )

        if config.knowledge.embedding_model:
            await _upsert_langflow_global_variable(
                "SELECTED_EMBEDDING_MODEL", config.knowledge.embedding_model, modify=True
            )
            logger.info(
                f"Set SELECTED_EMBEDDING_MODEL global variable to {config.knowledge.embedding_model}"
            )

    except Exception as e:
        logger.error(f"Failed to update Langflow global variables: {str(e)}")
        raise


async def _run_async_post_save_langflow_updates(
    session_manager,
    update_mcp_servers: bool,
    update_model_values: bool,
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

        # Update model values if provider/model changed (including removals/fallbacks)
        if update_model_values:
            await _update_langflow_model_values(
                current_config,
                flows_service,
                llm_model=current_config.agent.llm_model,
                llm_provider=current_config.agent.llm_provider,
                embedding_model=current_config.knowledge.embedding_model,
                embedding_provider=current_config.knowledge.embedding_provider,
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


async def _update_langflow_model_values(
    config,
    flows_service,
    llm_model=None,
    llm_provider=None,
    embedding_model=None,
    embedding_provider=None,
):
    """Update model values across Langflow flows for all configured providers"""
    try:
        if llm_model or llm_provider:
            effective_llm_provider = (llm_provider or config.agent.llm_provider).lower()
            if llm_provider and llm_provider.lower() != config.agent.llm_provider.lower():
                effective_llm_model = llm_model  # do not fall back; force caller to specify
            else:
                effective_llm_model = llm_model or config.agent.llm_model
            if effective_llm_provider not in LANGFLOW_MODEL_VALUE_PROVIDERS:
                logger.debug(
                    f"Skipping Langflow flow sync for LLM provider {effective_llm_provider} "
                    "(not routable through Langflow's unified flow components)"
                )
            else:
                result = await flows_service.change_langflow_model_value(
                    effective_llm_provider, llm_model=effective_llm_model, force_llm_update=True
                )

                logger.info(
                    f"Successfully updated Langflow flows for LLM provider {effective_llm_provider}",
                    result=result,
                )

        if embedding_model or embedding_provider:
            effective_embedding_provider = (
                embedding_provider or config.knowledge.embedding_provider
            ).lower()
            if (
                embedding_provider
                and embedding_provider.lower() != config.knowledge.embedding_provider.lower()
            ):
                effective_embedding_model = (
                    embedding_model  # do not fall back; force caller to specify
                )
            else:
                effective_embedding_model = embedding_model or config.knowledge.embedding_model
            if effective_embedding_provider not in LANGFLOW_MODEL_VALUE_PROVIDERS:
                logger.debug(
                    f"Skipping Langflow flow sync for embedding provider "
                    f"{effective_embedding_provider} "
                    "(not routable through Langflow's unified flow components)"
                )
            else:
                result = await flows_service.change_langflow_model_value(
                    effective_embedding_provider,
                    embedding_model=effective_embedding_model,
                    force_embedding_update=True,
                )

                logger.info(
                    f"Successfully updated Langflow flows for embedding provider "
                    f"{effective_embedding_provider}",
                    result=result,
                )

        if not (embedding_model or embedding_provider or llm_model or llm_provider):
            # 1. Update ALL configured LLM providers.
            # Regression fix (#1587): the no-argument fallback used by
            # reapply_all_settings previously only reapplied embedding providers,
            # leaving LLM model values unset whenever flows were reset.
            llm_providers = _configured_provider_names(config, _LLM_PROVIDER_NAMES)

            current_llm_provider = config.agent.llm_provider.lower()
            for provider in llm_providers:
                if provider not in LANGFLOW_MODEL_VALUE_PROVIDERS:
                    logger.debug(f"Skipping Langflow flow sync for provider {provider}")
                    continue
                # Use configured model for current provider, or None (first available) for others
                provider_llm_model = (
                    config.agent.llm_model if provider == current_llm_provider else None
                )
                await flows_service.change_langflow_model_value(
                    provider, llm_model=provider_llm_model, force_llm_update=True
                )
                logger.info(f"Successfully updated Langflow flows for LLM provider {provider}")

            # 2. Update ALL configured embedding providers
            embedding_providers = []
            if config.providers.openai.configured:
                embedding_providers.append("openai")
            if config.providers.watsonx.configured:
                embedding_providers.append("watsonx")
            if config.providers.ollama.configured:
                embedding_providers.append("ollama")

            current_embedding_provider = config.knowledge.embedding_provider.lower()
            for provider in embedding_providers:
                if provider not in LANGFLOW_MODEL_VALUE_PROVIDERS:
                    logger.debug(f"Skipping Langflow flow sync for provider {provider}")
                    continue
                # Use configured model for current provider, or None (first available) for others
                embedding_model = (
                    config.knowledge.embedding_model
                    if provider == current_embedding_provider
                    else None
                )
                await flows_service.change_langflow_model_value(
                    provider, embedding_model=embedding_model, force_embedding_update=True
                )
                logger.info(
                    f"Successfully updated Langflow flows for embedding provider {provider}"
                )
    except Exception as e:
        logger.error(f"Failed to update Langflow model values: {str(e)}")
        raise


async def _update_langflow_system_prompt(config, flows_service):
    """Update system prompt in chat flow"""
    try:
        llm_provider = config.agent.llm_provider.lower()
        await flows_service.update_chat_flow_system_prompt(config.agent.system_prompt, llm_provider)
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
