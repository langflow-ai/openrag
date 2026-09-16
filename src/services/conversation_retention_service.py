from config.config_manager import ConfigManager

# Hard cap imposed by this service — no workspace can prune more aggressively
# than 1 day or more lazily than 90 days.
RETENTION_DAYS_MIN = 1
RETENTION_DAYS_MAX = 90


class ConversationRetentionService:
    """Service for managing conversation retention policy."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    async def is_pruning_enabled(self) -> bool:
        """Check if conversation pruning is currently enabled."""
        config = self.config_manager.get_config()
        return config.conversation.pruning_enabled

    async def get_retention_days(self, operator_ttl_days: int) -> int:
        """Return the effective retention period in days.

        The workspace value (set via the settings UI) takes precedence when
        present and within bounds.  Falls back to the operator-configured TTL
        (``OPENRAG_CONVERSATION_TTL_DAYS``).  The result is always clamped to
        [RETENTION_DAYS_MIN, RETENTION_DAYS_MAX].
        """
        config = self.config_manager.get_config()
        workspace_days = config.conversation.retention_days
        days = workspace_days if workspace_days is not None else operator_ttl_days
        return max(RETENTION_DAYS_MIN, min(RETENTION_DAYS_MAX, days))

    async def set_pruning_enabled(self, enabled: bool) -> None:
        """Update the conversation pruning enabled flag."""
        config = self.config_manager.get_config()
        previous_value = config.conversation.pruning_enabled
        config.conversation.pruning_enabled = enabled
        try:
            # preserve_edited=True prevents marking config as edited during pre-onboarding toggle
            if not self.config_manager.save_config_file(config, preserve_edited=True):
                config.conversation.pruning_enabled = previous_value
                raise RuntimeError("Failed to save configuration")
        except Exception:
            config.conversation.pruning_enabled = previous_value
            raise

    async def set_retention_days(self, days: int, operator_ttl_days: int) -> None:
        """Persist a new user-chosen retention period.

        Raises ``ValueError`` if ``days`` is outside [RETENTION_DAYS_MIN,
        RETENTION_DAYS_MAX] or exceeds the operator cap.
        """
        if not (RETENTION_DAYS_MIN <= days <= RETENTION_DAYS_MAX):
            raise ValueError(
                f"retention_days must be between {RETENTION_DAYS_MIN} and "
                f"{RETENTION_DAYS_MAX}, got {days}"
            )
        if operator_ttl_days > 0 and days > operator_ttl_days:
            raise ValueError(
                f"retention_days ({days}) cannot exceed the operator-configured "
                f"TTL ({operator_ttl_days} days)"
            )

        config = self.config_manager.get_config()
        previous_value = config.conversation.retention_days
        config.conversation.retention_days = days
        try:
            if not self.config_manager.save_config_file(config, preserve_edited=True):
                config.conversation.retention_days = previous_value
                raise RuntimeError("Failed to save configuration")
        except Exception:
            config.conversation.retention_days = previous_value
            raise
