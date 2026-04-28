"""Configuration management for OpenRAG."""

import hashlib
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from utils.logging_config import get_logger

logger = get_logger(__name__)


DEFAULT_SYSTEM_PROMPT = """You are the OpenRAG Agent. You answer questions using retrieval, reasoning, and tool use.
You have access to several tools. Your job is to determine **which tool to use and when**.
### Available Tools
- OpenSearch Retrieval Tool:
  Use this to search the indexed knowledge base. Use when the user asks about product details, internal concepts, processes, architecture, documentation, roadmaps, or anything that may be stored in the index.
- Conversation History:
  Use this to maintain continuity when the user is referring to previous turns.
  Do not treat history as a factual source.
- Conversation File Context:
  Use this when the user asks about a document they uploaded or refers directly to its contents.
- Calculator / Expression Evaluation Tool:
  Use this when the user asks to compare numbers, compute estimates, calculate totals, analyze pricing, or answer any question requiring mathematics or quantitative reasoning.
  If the answer requires arithmetic, call the calculator tool rather than calculating internally.
### Retrieval Decision Rules
Use OpenSearch **whenever**:
1. The question may be answered from internal or indexed data.
2. The user references team names, product names, release plans, configurations, requirements, or official information.
3. The user needs a factual, grounded answer.
Do **not** use retrieval if:
- The question is purely creative (e.g., storytelling, analogies) or personal preference.
- The user simply wants text reformatted or rewritten from what is already present in the conversation.
When uncertain -> **Retrieve.** Retrieval is low risk and improves grounding.
### URL Handling
URL ingestion is disabled. Do not attempt to fetch, crawl, summarize, or ingest web URLs. If a user asks about a URL, explain that URL ingestion is unavailable.
### Calculator Usage Rules
Use the calculator when:
- Performing arithmetic
- Estimating totals
- Comparing values
- Modeling cost, time, effort, scale, or projections
Do not perform math internally. **Call the calculator tool instead.**
### Answer Construction Rules
1. When asked: "What is OpenRAG", answer the following:
"OpenRAG is an open-source package for building agentic RAG systems. It supports integration with a wide range of orchestration tools, vector databases, and LLM providers. OpenRAG connects and amplifies three popular, proven open-source projects into one powerful platform:
**Langflow** - Langflow is a powerful tool to build and deploy AI agents and MCP servers [Read more](https://www.langflow.org/)
**OpenSearch** - OpenSearch is an open source, search and observability suite that brings order to unstructured data at scale. [Read more](https://opensearch.org/)
**Docling** - Docling simplifies document processing with advanced PDF understanding, OCR support, and seamless AI integrations. Parse PDFs, DOCX, PPTX, images & more. [Read more](https://www.docling.ai/)"
2. Synthesize retrieved or ingested content in your own words.
3. Support factual claims with citations in the format:
   (Source: <document_name_or_id>)
4. If no supporting evidence is found:
   Say: "No relevant supporting sources were found for that request."
5. Never invent facts or hallucinate details.
6. Be concise, direct, and confident.
7. Do not reveal internal chain-of-thought."""

LEGACY_DEFAULT_SYSTEM_PROMPT_HASHES = frozenset(
    {
        # Normalized SHA-256 of the release-saas-0.1 default prompt that included URL ingestion.
        "768465010dfad0cbe054c0a5d3044004d374f8fcfa5d688ac2e0d2f6ff75ad22",
    }
)


def _normalized_prompt_hash(system_prompt: str) -> str:
    normalized_prompt = " ".join((system_prompt or "").split())
    return hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()


def _is_legacy_default_system_prompt(system_prompt: str) -> bool:
    return _normalized_prompt_hash(system_prompt) in LEGACY_DEFAULT_SYSTEM_PROMPT_HASHES


@dataclass
class OpenAIConfig:
    """OpenAI provider configuration."""
    api_key: str = ""
    configured: bool = False


@dataclass
class AnthropicConfig:
    """Anthropic provider configuration."""
    api_key: str = ""
    configured: bool = False


@dataclass
class WatsonXConfig:
    """IBM WatsonX provider configuration."""
    api_key: str = ""
    endpoint: str = ""
    project_id: str = ""
    configured: bool = False


@dataclass
class OllamaConfig:
    """Ollama provider configuration."""
    endpoint: str = ""
    resolved_endpoint: str = ""
    configured: bool = False


@dataclass
class ProvidersConfig:
    """All provider configurations."""
    openai: OpenAIConfig
    anthropic: AnthropicConfig
    watsonx: WatsonXConfig
    ollama: OllamaConfig

    def any_configured(self) -> bool:
        """Return True if at least one provider is marked as configured."""
        return any(p.configured for p in (self.openai, self.anthropic, self.watsonx, self.ollama))

    def get_provider_config(self, provider: str):
        """Get configuration for a specific provider."""
        provider_lower = provider.lower()
        if provider_lower == "openai":
            return self.openai
        elif provider_lower == "anthropic":
            return self.anthropic
        elif provider_lower == "watsonx":
            return self.watsonx
        elif provider_lower == "ollama":
            return self.ollama
        else:
            raise ValueError(f"Unknown provider: {provider}")


@dataclass
class KnowledgeConfig:
    """Knowledge/ingestion configuration."""

    embedding_model: str = ""
    embedding_provider: str = "openai"  # Which provider to use for embeddings
    chunk_size: int = 1000
    chunk_overlap: int = 200
    table_structure: bool = True
    ocr: bool = False
    picture_descriptions: bool = False
    index_name: str = "documents"  # OpenSearch index name


@dataclass
class AgentConfig:
    """Agent configuration."""

    llm_model: str = ""
    llm_provider: str = "openai"  # Which provider to use for LLM
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    def __post_init__(self):
        if _is_legacy_default_system_prompt(self.system_prompt):
            self.system_prompt = DEFAULT_SYSTEM_PROMPT


@dataclass
class OnboardingState:
    """Onboarding state configuration."""

    current_step: int = 0
    assistant_message: Optional[Dict[str, Any]] = field(default=None)
    selected_nudge: Optional[str] = field(default=None)
    card_steps: Optional[Dict[str, Any]] = field(default=None)
    upload_steps: Optional[Dict[str, Any]] = field(default=None)
    openrag_docs_filter_id: Optional[str] = field(default=None)
    user_doc_filter_id: Optional[str] = field(default=None)
    openrag_docs_ingested_version: Optional[str] = field(default=None)
    openrag_docs_remote_signature: Optional[str] = field(default=None)


@dataclass
class OpenRAGConfig:
    """Complete OpenRAG configuration."""

    providers: ProvidersConfig
    knowledge: KnowledgeConfig
    agent: AgentConfig
    onboarding: OnboardingState
    edited: bool = False  # Track if manually edited

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenRAGConfig":
        """Create config from dictionary."""
        providers_data = data.get("providers", {})
        
        # Import inside to avoid circular dependencies if any
        from utils.encryption import decrypt_secret
        
        def _decrypt_provider(p_data: dict) -> dict:
            new_data = dict(p_data)
            if "api_key" in new_data:
                new_data["api_key"] = decrypt_secret(new_data["api_key"])
            return new_data
            
        return cls(
            providers=ProvidersConfig(
                openai=OpenAIConfig(**_decrypt_provider(providers_data.get("openai", {}))),
                anthropic=AnthropicConfig(**_decrypt_provider(providers_data.get("anthropic", {}))),
                watsonx=WatsonXConfig(**_decrypt_provider(providers_data.get("watsonx", {}))),
                ollama=OllamaConfig(**_decrypt_provider(providers_data.get("ollama", {}))),
            ),
            knowledge=KnowledgeConfig(**data.get("knowledge", {})),
            agent=AgentConfig(**data.get("agent", {})),
            onboarding=OnboardingState(**data.get("onboarding", {})),
            edited=data.get("edited", False),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)

    def get_llm_provider_config(self):
        """Get the provider configuration for the current LLM provider."""
        return self.providers.get_provider_config(self.agent.llm_provider)

    def get_embedding_provider_config(self):
        """Get the provider configuration for the current embedding provider."""
        return self.providers.get_provider_config(self.knowledge.embedding_provider)


class ConfigManager:
    """Manages OpenRAG configuration from multiple sources."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize configuration manager.

        Args:
            config_file: Path to configuration file. If None, resolved lazily
                from OPENRAG_CONFIG_PATH on first access.
        """
        self._config_file: Optional[Path] = Path(config_file) if config_file else None
        self._config: Optional[OpenRAGConfig] = None

    @property
    def config_file(self) -> Path:
        """Lazily resolve config file path on first access."""
        if self._config_file is None:
            from config.paths import get_config_file_path
            self._config_file = Path(get_config_file_path())
        return self._config_file

    def load_config(self) -> OpenRAGConfig:
        """Load configuration from environment variables and config file.

        Priority order:
        1. Environment variables (highest)
        2. Configuration file
        3. Defaults (lowest)
        """
        if self._config is not None:
            return self._config

        # Start with defaults
        config_data = {
            "providers": {
                "openai": {},
                "anthropic": {},
                "watsonx": {},
                "ollama": {},
            },
            "knowledge": {},
            "agent": {},
            "onboarding": {},
        }
        
        needs_encryption_upgrade = False
        from utils.encryption import get_master_secret

        # Load from config file if it exists
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    file_config = yaml.safe_load(f) or {}

                # Merge file config
                if "providers" in file_config:
                    for provider in ["openai", "anthropic", "watsonx", "ollama"]:
                        if provider in file_config["providers"]:
                            provider_data = file_config["providers"][provider]
                            # Check if api_key is unencrypted and we have a key
                            if "api_key" in provider_data and isinstance(provider_data["api_key"], str) and provider_data["api_key"]:
                                if get_master_secret() is not None:
                                    needs_encryption_upgrade = True
                            config_data["providers"][provider].update(provider_data)
                for section in ["knowledge", "agent", "onboarding"]:
                    if section in file_config:
                        config_data[section].update(file_config[section])

                config_data["edited"] = file_config.get("edited", False)

                logger.info(f"Loaded configuration from {self.config_file}")
            except Exception as e:
                logger.warning(f"Failed to load config file {self.config_file}: {e}")

        # Create config object first to check edited flags
        temp_config = OpenRAGConfig.from_dict(config_data)

        # Override with environment variables (highest priority, but respect edited flags)
        self._load_env_overrides(config_data, temp_config)

        # Create config object
        self._config = OpenRAGConfig.from_dict(config_data)

        if needs_encryption_upgrade:
            logger.info("Upgrading unencrypted secrets in config.yaml to AES-256-GCM")
            self.save_config_file(self._config, preserve_edited=True)

        logger.debug("[CONFIG] Configuration loaded successfully")
        return self._config

    def _load_env_overrides(
        self, config_data: Dict[str, Any], temp_config: Optional["OpenRAGConfig"] = None
    ) -> None:
        """Load environment variable overrides, respecting edited flag."""

        # Skip all environment overrides if config has been manually edited
        if temp_config and temp_config.edited:
            logger.debug("Skipping all env overrides - config marked as edited")
            return

        # OpenAI provider settings
        if os.getenv("OPENAI_API_KEY"):
            config_data["providers"]["openai"]["api_key"] = os.getenv("OPENAI_API_KEY")

        # Anthropic provider settings
        if os.getenv("ANTHROPIC_API_KEY"):
            config_data["providers"]["anthropic"]["api_key"] = os.getenv("ANTHROPIC_API_KEY")

        # WatsonX provider settings
        if os.getenv("WATSONX_API_KEY"):
            config_data["providers"]["watsonx"]["api_key"] = os.getenv("WATSONX_API_KEY")
        if os.getenv("WATSONX_ENDPOINT"):
            config_data["providers"]["watsonx"]["endpoint"] = os.getenv("WATSONX_ENDPOINT")
        if os.getenv("WATSONX_PROJECT_ID"):
            config_data["providers"]["watsonx"]["project_id"] = os.getenv("WATSONX_PROJECT_ID")

        # Ollama provider settings
        if os.getenv("OLLAMA_ENDPOINT"):
            config_data["providers"]["ollama"]["endpoint"] = os.getenv("OLLAMA_ENDPOINT")

        # Knowledge settings
        if os.getenv("EMBEDDING_MODEL"):
            config_data["knowledge"]["embedding_model"] = os.getenv("EMBEDDING_MODEL")
        if os.getenv("EMBEDDING_PROVIDER"):
            config_data["knowledge"]["embedding_provider"] = os.getenv("EMBEDDING_PROVIDER")
        if os.getenv("CHUNK_SIZE"):
            config_data["knowledge"]["chunk_size"] = int(os.getenv("CHUNK_SIZE"))
        if os.getenv("CHUNK_OVERLAP"):
            config_data["knowledge"]["chunk_overlap"] = int(os.getenv("CHUNK_OVERLAP"))
        if os.getenv("OPENSEARCH_INDEX_NAME"):
            config_data["knowledge"]["index_name"] = os.getenv("OPENSEARCH_INDEX_NAME")
        if os.getenv("OCR_ENABLED"):
            config_data["knowledge"]["ocr"] = os.getenv("OCR_ENABLED").lower() in (
                "true",
                "1",
                "yes",
            )
        if os.getenv("PICTURE_DESCRIPTIONS_ENABLED"):
            config_data["knowledge"]["picture_descriptions"] = os.getenv(
                "PICTURE_DESCRIPTIONS_ENABLED"
            ).lower() in ("true", "1", "yes")

        # Agent settings
        if os.getenv("LLM_MODEL"):
            config_data["agent"]["llm_model"] = os.getenv("LLM_MODEL")
        if os.getenv("LLM_PROVIDER"):
            config_data["agent"]["llm_provider"] = os.getenv("LLM_PROVIDER")
        if os.getenv("SYSTEM_PROMPT"):
            config_data["agent"]["system_prompt"] = os.getenv("SYSTEM_PROMPT")

    def get_config(self) -> OpenRAGConfig:
        """Get current configuration, loading if necessary."""
        if self._config is None:
            return self.load_config()
        return self._config

    def reload_config(self) -> OpenRAGConfig:
        """Force reload configuration from sources."""
        self._config = None
        return self.load_config()

    def save_config_file(self, config: Optional[OpenRAGConfig] = None, preserve_edited: bool = False) -> bool:
        """Save configuration to file.

        Args:
            config: Configuration to save. If None, uses current config.
            preserve_edited: If True, do not forcefully set the 'edited' flag upon saving.

        Returns:
            True if saved successfully, False otherwise.
        """
        if config is None:
            config = self.get_config()

        # Mark config as edited when saving manually
        if not preserve_edited:
            config.edited = True

        try:
            # Ensure directory exists
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            config_dict = config.to_dict()
            
            # Encrypt provider API keys before saving
            from utils.encryption import encrypt_secret
            providers = config_dict.get("providers", {})
            for provider_name, provider_config in providers.items():
                if "api_key" in provider_config:
                    provider_config["api_key"] = encrypt_secret(provider_config["api_key"])

            with open(self.config_file, "w") as f:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)

            # Update cached config to reflect the edited flags
            self._config = config

            logger.info(f"Configuration saved to {self.config_file} - marked as edited")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration to {self.config_file}: {e}")
            raise e

    def update_onboarding_state(self, **kwargs) -> bool:
        """Update onboarding state fields.

        Args:
            **kwargs: Onboarding state fields to update (current_step, assistant_message, etc.)

        Returns:
            True if updated successfully, False otherwise.
        """
        try:
            config = self.get_config()
            
            # Update only the provided fields
            for key, value in kwargs.items():
                if hasattr(config.onboarding, key):
                    setattr(config.onboarding, key, value)
                else:
                    logger.warning(f"Unknown onboarding field: {key}")
            
            # Save the updated config
            return self.save_config_file(config)
        except Exception as e:
            logger.error(f"Failed to update onboarding state: {e}")
            return False


# Global config manager instance
config_manager = ConfigManager()
