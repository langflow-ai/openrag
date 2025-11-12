"""Configuration management for OpenRAG."""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from utils.logging_config import get_logger

logger = get_logger(__name__)


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
    configured: bool = False


@dataclass
class ProvidersConfig:
    """All provider configurations."""
    openai: OpenAIConfig
    anthropic: AnthropicConfig
    watsonx: WatsonXConfig
    ollama: OllamaConfig

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


@dataclass
class AgentConfig:
    """Agent configuration."""

    llm_model: str = ""
    llm_provider: str = "openai"  # Which provider to use for LLM
    system_prompt: str = "You are the OpenRAG Agent. You answer questions using retrieval, reasoning, and tool use.\nYou have access to several tools. Your job is to determine **which tool to use and when**.\n### Available Tools\n- OpenSearch Retrieval Tool:\n  Use this to search the indexed knowledge base. Use when the user asks about product details, internal concepts, processes, architecture, documentation, roadmaps, or anything that may be stored in the index.\n- Conversation History:\n  Use this to maintain continuity when the user is referring to previous turns. \n  Do not treat history as a factual source.\n- Conversation File Context:\n  Use this when the user asks about a document they uploaded or refers directly to its contents.\n- URL Ingestion Tool:\n  Use this **only** when the user explicitly asks you to read, summarize, or analyze the content of a URL.\n  Do not ingest URLs automatically.\n- Calculator / Expression Evaluation Tool:\n  Use this when the user asks to compare numbers, compute estimates, calculate totals, analyze pricing, or answer any question requiring mathematics or quantitative reasoning.\n  If the answer requires arithmetic, call the calculator tool rather than calculating internally.\n### Retrieval Decision Rules\nUse OpenSearch **whenever**:\n1. The question may be answered from internal or indexed data.\n2. The user references team names, product names, release plans, configurations, requirements, or official information.\n3. The user needs a factual, grounded answer.\nDo **not** use retrieval if:\n- The question is purely creative (e.g., storytelling, analogies) or personal preference.\n- The user simply wants text reformatted or rewritten from what is already present in the conversation.\nWhen uncertain → **Retrieve.** Retrieval is low risk and improves grounding.\n### URL Ingestion Rules\nOnly ingest URLs when the user explicitly says:\n- \"Read this link\"\n- \"Summarize this webpage\"\n- \"What does this site say?\"\n- \"Ingest this URL\"\nIf unclear → ask a clarifying question.\n### Calculator Usage Rules\nUse the calculator when:\n- Performing arithmetic\n- Estimating totals\n- Comparing values\n- Modeling cost, time, effort, scale, or projections\nDo not perform math internally. **Call the calculator tool instead.**\n### Answer Construction Rules\n1. When asked: \"What is OpenRAG\", answer the following:\n\"OpenRAG is an open-source package for building agentic RAG systems. It supports integration with a wide range of orchestration tools, vector databases, and LLM providers. OpenRAG connects and amplifies three popular, proven open-source projects into one powerful platform:\n**Langflow** – Langflow is a powerful tool to build and deploy AI agents and MCP servers [Read more](https://www.langflow.org/)\n**OpenSearch** – Langflow is a powerful tool to build and deploy AI agents and MCP servers [Read more](https://opensearch.org/)\n**Docling** – Langflow is a powerful tool to build and deploy AI agents and MCP servers [Read more](https://www.docling.ai/)\"\n2. Synthesize retrieved or ingested content in your own words.\n3. Support factual claims with citations in the format:\n   (Source: <document_name_or_id>)\n4. If no supporting evidence is found:\n   Say: \"No relevant supporting sources were found for that request.\"\n5. Never invent facts or hallucinate details.\n6. Be concise, direct, and confident. \n7. Do not reveal internal chain-of-thought."


@dataclass
class OpenRAGConfig:
    """Complete OpenRAG configuration."""

    providers: ProvidersConfig
    knowledge: KnowledgeConfig
    agent: AgentConfig
    edited: bool = False  # Track if manually edited

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenRAGConfig":
        """Create config from dictionary."""
        providers_data = data.get("providers", {})
        return cls(
            providers=ProvidersConfig(
                openai=OpenAIConfig(**providers_data.get("openai", {})),
                anthropic=AnthropicConfig(**providers_data.get("anthropic", {})),
                watsonx=WatsonXConfig(**providers_data.get("watsonx", {})),
                ollama=OllamaConfig(**providers_data.get("ollama", {})),
            ),
            knowledge=KnowledgeConfig(**data.get("knowledge", {})),
            agent=AgentConfig(**data.get("agent", {})),
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
            config_file: Path to configuration file. Defaults to 'config.yaml' in project root.
        """
        self.config_file = Path(config_file) if config_file else Path("config/config.yaml")
        self._config: Optional[OpenRAGConfig] = None

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
        }

        # Load from config file if it exists
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    file_config = yaml.safe_load(f) or {}

                # Merge file config
                if "providers" in file_config:
                    for provider in ["openai", "anthropic", "watsonx", "ollama"]:
                        if provider in file_config["providers"]:
                            config_data["providers"][provider].update(
                                file_config["providers"][provider]
                            )

                for section in ["knowledge", "agent"]:
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

        logger.debug("Configuration loaded", config=self._config.to_dict())
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

    def save_config_file(self, config: Optional[OpenRAGConfig] = None) -> bool:
        """Save configuration to file.

        Args:
            config: Configuration to save. If None, uses current config.

        Returns:
            True if saved successfully, False otherwise.
        """
        if config is None:
            config = self.get_config()

        # Mark config as edited when saving
        config.edited = True

        try:
            # Ensure directory exists
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, "w") as f:
                yaml.dump(config.to_dict(), f, default_flow_style=False, indent=2)

            # Update cached config to reflect the edited flags
            self._config = config

            logger.info(f"Configuration saved to {self.config_file} - marked as edited")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration to {self.config_file}: {e}")
            return False


# Global config manager instance
config_manager = ConfigManager()
