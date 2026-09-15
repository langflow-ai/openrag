"""Conversation retention policy service.

Manages the conversation pruning policy (enabled/disabled flag) that controls
whether the nightly pruning task deletes stale conversations.
"""

from config.config_manager import ConfigManager


class ConversationRetentionService:
    """Service for managing conversation retention policy."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    async def is_pruning_enabled(self) -> bool:
        """Check if conversation pruning is currently enabled."""
        config = self.config_manager.get_config()
        return config.conversation.pruning_enabled

    async def set_pruning_enabled(self, enabled: bool) -> None:
        """Update the conversation pruning enabled flag."""
        config = self.config_manager.get_config()
        previous_value = config.conversation.pruning_enabled
        config.conversation.pruning_enabled = enabled
        try:
            if not self.config_manager.save_config_file(config):
                # Restore previous value and raise
                config.conversation.pruning_enabled = previous_value
                raise RuntimeError("Failed to save configuration")
        except Exception:
            # Restore previous value on any exception
            config.conversation.pruning_enabled = previous_value
            raise
