"""Configuration management for OpenRAG."""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ProviderConfig:
    """Model provider configuration."""

    model_provider: str = "openai"  # openai, anthropic, etc.
    api_key: str = ""
    endpoint: str = ""  # For providers like Watson/IBM that need custom endpoints
    project_id: str = ""  # For providers like Watson/IBM that need project IDs


@dataclass
class KnowledgeConfig:
    """Knowledge/ingestion configuration."""

    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    table_structure: bool = True
    ocr: bool = False
    picture_descriptions: bool = False


@dataclass
class AgentConfig:
    """Agent configuration."""

    llm_model: str = "gpt-4o-mini"
    system_prompt: str = "You are a helpful AI assistant with access to a knowledge base. Answer questions based on the provided context."


@dataclass
class OpenRAGConfig:
    """Complete OpenRAG configuration."""

    provider: ProviderConfig
    knowledge: KnowledgeConfig
    agent: AgentConfig
    edited: bool = False  # Track if manually edited

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenRAGConfig":
        """Create config from dictionary."""
        return cls(
            provider=ProviderConfig(**data.get("provider", {})),
            knowledge=KnowledgeConfig(**data.get("knowledge", {})),
            agent=AgentConfig(**data.get("agent", {})),
            edited=data.get("edited", False),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)


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
        config_data = {"provider": {}, "knowledge": {}, "agent": {}}

        # Load from config file if it exists
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    file_config = yaml.safe_load(f) or {}

                # Merge file config
                for section in ["provider", "knowledge", "agent"]:
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

        # Provider settings
        if os.getenv("MODEL_PROVIDER"):
            config_data["provider"]["model_provider"] = os.getenv("MODEL_PROVIDER")
        if os.getenv("PROVIDER_API_KEY"):
            config_data["provider"]["api_key"] = os.getenv("PROVIDER_API_KEY")
        if os.getenv("PROVIDER_ENDPOINT"):
            config_data["provider"]["endpoint"] = os.getenv("PROVIDER_ENDPOINT")
        if os.getenv("PROVIDER_PROJECT_ID"):
            config_data["provider"]["project_id"] = os.getenv("PROVIDER_PROJECT_ID")
        # Backward compatibility for OpenAI
        if os.getenv("OPENAI_API_KEY"):
            config_data["provider"]["api_key"] = os.getenv("OPENAI_API_KEY")
            if not config_data["provider"].get("model_provider"):
                config_data["provider"]["model_provider"] = "openai"

        # Knowledge settings
        if os.getenv("EMBEDDING_MODEL"):
            config_data["knowledge"]["embedding_model"] = os.getenv("EMBEDDING_MODEL")
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
