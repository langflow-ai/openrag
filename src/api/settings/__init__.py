"""Settings/onboarding endpoint package.

The original `src/api/settings.py` (2081 lines) was split into focused
submodules. This `__init__.py` preserves the public-import contract every
external caller relies on:

* `src/app/routes/internal.py` registers each endpoint via
  `from api import settings; app.add_api_route(..., settings.<name>, ...)`.
* `src/api/v1/settings.py` imports `SettingsUpdateBody` and (lazily)
  `update_settings`.
* `src/services/startup_orchestrator.py` lazily imports
  `reapply_all_settings` for flow-reset re-sync.

Adding a new endpoint to this package: define it in `endpoints.py`, then
re-export it here.
"""

from api.settings.endpoints import (
    get_settings,
    onboarding,
    refresh_openrag_docs,
    rollback_onboarding,
    update_docling_preset,
    update_onboarding_state,
    update_settings,
)
from api.settings.langflow_sync import reapply_all_settings
from api.settings.models import (
    AgentConfig,
    AnthropicProviderConfig,
    AssistantMessage,
    DoclingPresetBody,
    DoclingPresetResponse,
    IngestionDefaultsConfig,
    KnowledgeConfig,
    OllamaProviderConfig,
    OnboardingBody,
    OnboardingResponse,
    OnboardingStateBody,
    OnboardingStateConfig,
    OnboardingStateResponse,
    OpenAIProviderConfig,
    ProvidersConfig,
    RefreshOpenRAGDocsResponse,
    RollbackBody,
    RollbackResponse,
    SettingsResponse,
    SettingsUpdateBody,
    SettingsUpdateResponse,
    WatsonXProviderConfig,
)

__all__ = [
    # Endpoints
    "get_settings",
    "update_settings",
    "onboarding",
    "update_onboarding_state",
    "rollback_onboarding",
    "update_docling_preset",
    "refresh_openrag_docs",
    # Internal orchestrator (called from services/startup_orchestrator.py)
    "reapply_all_settings",
    # Pydantic models (some are imported externally; re-export all for parity
    # with the pre-split flat module's surface)
    "SettingsUpdateBody",
    "OnboardingBody",
    "AssistantMessage",
    "OnboardingStateBody",
    "DoclingPresetBody",
    "OnboardingStateConfig",
    "OpenAIProviderConfig",
    "AnthropicProviderConfig",
    "WatsonXProviderConfig",
    "OllamaProviderConfig",
    "ProvidersConfig",
    "KnowledgeConfig",
    "AgentConfig",
    "IngestionDefaultsConfig",
    "SettingsResponse",
    "OnboardingResponse",
    "RefreshOpenRAGDocsResponse",
    "DoclingPresetResponse",
    "OnboardingStateResponse",
    "SettingsUpdateResponse",
    "RollbackResponse",
    "RollbackBody",
]
