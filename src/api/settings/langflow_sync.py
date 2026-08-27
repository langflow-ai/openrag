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
    _EMBEDDING_PROVIDER_NAMES,
    _LLM_PROVIDER_NAMES,
    _configured_provider_names,
    _get_flows_service,
)
from config import settings
from config.settings import clients, get_openrag_config
from services.docling_service import get_docling_preset_configs
from utils.langflow_headers import map_provider
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


def _required_generic_global_values(config) -> dict[str, str]:
    knowledge = getattr(config, "knowledge", None)
    providers = getattr(config, "providers", None)
    agent = getattr(config, "agent", None)
    watsonx = getattr(providers, "watsonx", None)
    ollama = getattr(providers, "ollama", None)

    return {
        "DOCLING_SERVE_URL": settings.get_langflow_docling_url(),
        "DOCLING_SERVE_VERIFY_SSL": str(settings.DOCLING_SERVE_VERIFY_SSL).lower(),
        "DOCLING_TASK_ID": "None",
        "FILESIZE": "0",
        "MIMETYPE": "None",
        "OLLAMA_BASE_URL": _string_value(getattr(ollama, "endpoint", None)),
        "OPENRAG-QUERY-FILTER": "{}",
        "OPENRAG_INGEST_BATCH_SIZE": "100",
        "OPENRAG_INGEST_RUN_ID": "OPENRAG_INGEST_RUN_ID",
        "OPENRAG_INGEST_TOKEN": "OPENRAG_INGEST_TOKEN",
        "OPENRAG_INGEST_URL": "OPENRAG_INGEST_URL",
        "OPENSEARCH_INDEX_NAME": _string_value(getattr(knowledge, "index_name", None))
        or "documents",
        "OPENSEARCH_URL": settings.get_langflow_opensearch_url(),
        "SELECTED_EMBEDDING_MODEL": _string_value(getattr(knowledge, "embedding_model", None))
        or "text-embedding-3-small",
        "SELECTED_EMBEDDING_MODEL_PROVIDER": map_provider(
            getattr(knowledge, "embedding_provider", None) or "openai"
        ),
        "SELECTED_LANGUAGE_MODEL": _string_value(getattr(agent, "llm_model", None))
        or "gpt-4o-mini",
        "SELECTED_LANGUAGE_MODEL_PROVIDER": map_provider(
            getattr(agent, "llm_provider", None) or "openai"
        ),
        "WATSONX_PROJECT_ID": _string_value(getattr(watsonx, "project_id", None)),
        "WATSONX_URL": _string_value(getattr(watsonx, "endpoint", None)),
    }


async def ensure_required_langflow_global_variables(config=None):
    """Ensure plain-string globals are Generic and remove any Apply To (default_fields) fields."""
    config = config or get_openrag_config()
    required_values = _required_generic_global_values(config)

    existing_by_name = {}
    try:
        response = await clients.langflow_request("GET", "/api/v1/variables/")
        if response.status_code == 200:
            existing_variables = response.json()
            existing_by_name = {v.get("name"): v for v in existing_variables if v.get("name")}
        else:
            logger.warning(
                "Could not fetch Langflow variables at startup",
                status_code=response.status_code,
            )
            return
    except Exception as e:
        logger.warning("Could not fetch Langflow variables at startup", error=str(e))
        return

    # Update or fix existing variables in a single operation per variable
    for name, var in existing_by_name.items():
        try:
            var_id = var.get("id")
            if not var_id:
                continue

            is_generic = name in LANGFLOW_GENERIC_GLOBAL_VARIABLES
            target_type = "Generic" if is_generic else var.get("type", "Credential")

            curr_type = var.get("type")
            curr_val = var.get("value", "")
            has_default_fields = bool(var.get("default_fields"))

            target_val = _string_value(required_values.get(name)) if is_generic else curr_val

            # Langflow rejects an empty value with 400 "Variable value cannot be
            # empty". Optional providers (Ollama, watsonx) resolve to "" when
            # unconfigured, so keep whatever Langflow already holds instead of
            # pushing a value it will refuse. This matters most in the type
            # migration below: the DELETE has already landed by then, so a
            # refused recreate would drop the variable entirely.
            sync_value = is_generic and bool(target_val)
            if not sync_value:
                target_val = curr_val

            if curr_type != target_type:
                if not target_val:
                    # The retained value (see sync_value above) is also empty: the
                    # DELETE below would succeed but the recreate POST would send ""
                    # and get rejected, dropping the variable entirely. Defer the
                    # type migration until the variable actually has a value.
                    logger.debug(
                        "Deferring Langflow global variable type migration until configured",
                        variable_name=name,
                        old_type=curr_type,
                        new_type=target_type,
                    )
                    continue

                logger.info(
                    "Migrating Langflow global variable type",
                    variable_name=name,
                    old_type=curr_type,
                    new_type=target_type,
                )
                del_resp = await clients.langflow_request("DELETE", f"/api/v1/variables/{var_id}")
                if not (200 <= del_resp.status_code < 300):
                    raise RuntimeError(
                        f"Failed to delete Langflow global variable {name!r}: status_code={del_resp.status_code}"
                    )
                recreate_payload = {
                    "name": name,
                    "value": target_val,
                    "default_fields": [],
                    "type": target_type,
                }
                recreate_resp = await clients.langflow_request(
                    "POST", "/api/v1/variables/", json=recreate_payload
                )
                if not (200 <= recreate_resp.status_code < 300):
                    raise RuntimeError(
                        f"Failed to recreate Langflow global variable {name!r}: status_code={recreate_resp.status_code}"
                    )
            elif has_default_fields or (sync_value and curr_val != target_val):
                logger.info(
                    "Updating Langflow global variable", variable_name=name, variable_id=var_id
                )
                patch_payload = {
                    "id": var_id,
                    "name": name,
                    "default_fields": [],
                    "type": target_type,
                }
                if sync_value:
                    patch_payload["value"] = target_val
                patch_resp = await clients.langflow_request(
                    "PATCH", f"/api/v1/variables/{var_id}", json=patch_payload
                )
                if not (200 <= patch_resp.status_code < 300):
                    raise RuntimeError(
                        f"Failed to patch Langflow global variable {name!r}: status_code={patch_resp.status_code}"
                    )
        except Exception as e:
            logger.warning(
                "Failed to update Langflow global variable", variable_name=name, error=str(e)
            )

    # Create missing generic variables
    for name in sorted(LANGFLOW_GENERIC_GLOBAL_VARIABLES):
        if name not in existing_by_name:
            try:
                target_val = _string_value(required_values.get(name, ""))
                if not target_val:
                    # Langflow rejects an empty value with 400. Variables sourced
                    # from an unconfigured optional provider (OLLAMA_BASE_URL,
                    # WATSONX_PROJECT_ID, WATSONX_URL) have nothing to set yet;
                    # they are created once that provider is configured.
                    logger.debug(
                        "Skipping Langflow global variable with no configured value",
                        variable_name=name,
                    )
                    continue
                await _upsert_langflow_global_variable(name, target_val)
            except Exception as e:
                logger.warning(
                    "Failed to create Langflow global variable", variable_name=name, error=str(e)
                )


async def _update_langflow_global_variables(config, flows_service=None):
    """Update Langflow global variables for all configured providers"""
    errors: list[str] = []

    async def _safe_upsert(name: str, value: str):
        try:
            await _upsert_langflow_global_variable(name, value)
            logger.info("Set global variable in Langflow", variable_name=name)
        except Exception as e:
            logger.warning(
                "Failed to set global variable in Langflow", variable_name=name, error=str(e)
            )
            errors.append(f"{name}: {e}")

    providers = getattr(config, "providers", None)

    # WatsonX global variables
    watsonx = getattr(providers, "watsonx", None)
    if watsonx:
        if getattr(watsonx, "api_key", None):
            await _safe_upsert("WATSONX_APIKEY", watsonx.api_key)

        if getattr(watsonx, "project_id", None):
            await _safe_upsert("WATSONX_PROJECT_ID", watsonx.project_id)

        if getattr(watsonx, "endpoint", None):
            await _safe_upsert("WATSONX_URL", watsonx.endpoint)

    # OpenAI global variables
    openai = getattr(providers, "openai", None)
    if openai and getattr(openai, "api_key", None):
        await _safe_upsert("OPENAI_API_KEY", openai.api_key)

    # Anthropic global variables
    anthropic = getattr(providers, "anthropic", None)
    if anthropic and getattr(anthropic, "api_key", None):
        await _safe_upsert("ANTHROPIC_API_KEY", anthropic.api_key)

    # Ollama global variables
    ollama = getattr(providers, "ollama", None)
    if ollama and getattr(ollama, "endpoint", None):
        try:
            if not flows_service:
                flows_service = _get_flows_service()

            endpoint = await flows_service.resolve_ollama_url(ollama.endpoint, force_refresh=True)
            await _safe_upsert("OLLAMA_BASE_URL", endpoint)
        except Exception as e:
            logger.warning("Failed to resolve OLLAMA_BASE_URL", error=str(e))
            errors.append(f"OLLAMA_BASE_URL resolution: {e}")

    knowledge = getattr(config, "knowledge", None)
    if getattr(knowledge, "embedding_model", None):
        await _safe_upsert("SELECTED_EMBEDDING_MODEL", config.knowledge.embedding_model)

    if getattr(knowledge, "embedding_provider", None):
        mapped_provider = map_provider(config.knowledge.embedding_provider)
        await _safe_upsert("SELECTED_EMBEDDING_MODEL_PROVIDER", mapped_provider)

    agent = getattr(config, "agent", None)
    if getattr(agent, "llm_model", None):
        await _safe_upsert("SELECTED_LANGUAGE_MODEL", config.agent.llm_model)

    if getattr(agent, "llm_provider", None):
        mapped_llm_provider = map_provider(config.agent.llm_provider)
        await _safe_upsert("SELECTED_LANGUAGE_MODEL_PROVIDER", mapped_llm_provider)

    if errors:
        raise RuntimeError(f"Failed to update Langflow global variable(s): {', '.join(errors)}")


async def _run_async_post_save_langflow_updates(
    session_manager,
    update_mcp_servers: bool,
    update_model_values: bool = False,
    models_service=None,
    update_llm: bool = True,
    update_embedding: bool = True,
    update_global_variables: bool = False,
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

        # Update global variables only when provider credentials or endpoints change
        if update_global_variables:
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
                llm_model=current_config.agent.llm_model if update_llm else None,
                llm_provider=current_config.agent.llm_provider if update_llm else None,
                embedding_model=current_config.knowledge.embedding_model
                if update_embedding
                else None,
                embedding_provider=current_config.knowledge.embedding_provider
                if update_embedding
                else None,
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
            result = await flows_service.change_langflow_model_value(
                effective_embedding_provider,
                embedding_model=effective_embedding_model,
                force_embedding_update=True,
            )

            logger.info(
                f"Successfully updated Langflow flows for embedding provider {effective_embedding_provider}",
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
                # Use configured model for current provider, or None (first available) for others
                provider_llm_model = (
                    config.agent.llm_model if provider == current_llm_provider else None
                )
                await flows_service.change_langflow_model_value(
                    provider, llm_model=provider_llm_model, force_llm_update=True
                )
                logger.info(f"Successfully updated Langflow flows for LLM provider {provider}")

            # 2. Update ALL configured embedding providers
            embedding_providers = _configured_provider_names(config, _EMBEDDING_PROVIDER_NAMES)

            current_embedding_provider = config.knowledge.embedding_provider.lower()
            for provider in embedding_providers:
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
