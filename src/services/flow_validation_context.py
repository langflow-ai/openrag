"""Context variable system for storing flow validation results per user."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ComponentParameter:
    """Information about a component parameter."""

    name: str
    display_name: str
    param_type: str
    value: Any = None
    options: Optional[List] = None
    advanced: bool = False
    required: bool = False


@dataclass
class ComponentInfo:
    """Information about a single component."""

    display_name: str
    component_type: str
    node_id: str
    parameters: Dict[str, ComponentParameter] = field(default_factory=dict)


@dataclass
class FlowComponentInfo:
    """Information about all components available in a flow."""

    components: Dict[str, List[ComponentInfo]] = field(default_factory=dict)
    validated_at: Optional[float] = None
    flow_id: Optional[str] = None

    @property
    def has_file(self) -> bool:
        return len(self.components.get("File", [])) > 0

    @property
    def has_split_text(self) -> bool:
        return len(self.components.get("Split Text", [])) > 0

    @property
    def has_openai_embeddings(self) -> bool:
        return len(self.components.get("OpenAI Embeddings", [])) > 0

    @property
    def has_opensearch_hybrid(self) -> bool:
        return len(self.components.get("OpenSearch (Hybrid)", [])) > 0

    @property
    def is_valid_for_ingestion(self) -> bool:
        """Check if flow has minimum required components for ingestion."""
        return (
            self.has_file
            and self.has_opensearch_hybrid
            and len(self.components.get("File", [])) == 1
        )

    def get_available_parameters(
        self, component_type: str
    ) -> Dict[str, ComponentParameter]:
        """Get available parameters for a specific component type."""
        components_of_type = self.components.get(component_type, [])
        if not components_of_type:
            return {}

        # Return parameters from first component of this type
        return components_of_type[0].parameters

    # Configuration for UI settings mapping (display names come from flow data)
    UI_SETTINGS_CONFIG = [
        {
            "component_display_name": "Split Text",
            "settings": [
                {"ui_setting": "chunkSize", "parameter_name": "chunk_size"},
                {"ui_setting": "chunkOverlap", "parameter_name": "chunk_overlap"},
                {"ui_setting": "separator", "parameter_name": "separator"},
            ],
        },
        {
            "component_display_name": "OpenAI Embeddings",
            "settings": [{"ui_setting": "embeddingModel", "parameter_name": "model"}],
        },
    ]

    @property
    def available_ui_settings(self) -> Dict[str, Any]:
        """Return which UI settings should be available with their parameter info."""
        settings = {}

        for config in self.UI_SETTINGS_CONFIG:
            component_name = config["component_display_name"]
            has_component = (
                component_name in self.components
                and len(self.components[component_name]) > 0
            )

            if has_component:
                component_params = self.get_available_parameters(component_name)

                for setting_config in config["settings"]:
                    ui_setting = setting_config["ui_setting"]
                    param_name = setting_config["parameter_name"]

                    param_available = param_name in component_params
                    param_info = (
                        component_params.get(param_name) if param_available else None
                    )

                    settings[ui_setting] = {
                        "available": param_available,
                        "component": component_name,
                        "parameter_name": param_name,
                        "param_info": {
                            "display_name": param_info.display_name,
                            "type": param_info.param_type,
                            "value": param_info.value,
                            "options": param_info.options,
                            "advanced": param_info.advanced,
                            "required": param_info.required,
                        }
                        if param_info
                        else None,
                    }
            else:
                # Component not present - mark all its settings as unavailable
                for setting_config in config["settings"]:
                    ui_setting = setting_config["ui_setting"]
                    settings[ui_setting] = {
                        "available": False,
                        "component": component_name,
                        "parameter_name": setting_config["parameter_name"],
                        "param_info": None,
                        "reason": f"Component '{component_name}' not found in flow",
                    }

        return settings

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses."""
        return {
            "components": {
                component_type: [
                    {
                        "display_name": comp.display_name,
                        "type": comp.component_type,
                        "node_id": comp.node_id,
                        "parameters": {
                            param_name: {
                                "display_name": param.display_name,
                                "type": param.param_type,
                                "value": param.value,
                                "options": param.options,
                                "advanced": param.advanced,
                                "required": param.required,
                            }
                            for param_name, param in comp.parameters.items()
                        },
                    }
                    for comp in component_list
                ]
                for component_type, component_list in self.components.items()
            },
            "validation": {
                "is_valid": self.is_valid_for_ingestion,
                "validated_at": self.validated_at,
                "flow_id": self.flow_id,
            },
            "available_ui_settings": self.available_ui_settings,
        }


# Context variable to store flow component info per request/user
_flow_context: ContextVar[Optional[FlowComponentInfo]] = ContextVar(
    "flow_validation_context", default=None
)

# Cache to store validation results per flow_id to avoid repeated API calls
_validation_cache: Dict[str, FlowComponentInfo] = {}
_cache_lock = asyncio.Lock()


async def get_flow_components(user_id: str) -> Optional[FlowComponentInfo]:
    """Get current flow component info from context."""
    return _flow_context.get()


async def set_flow_components(user_id: str, component_info: FlowComponentInfo) -> None:
    """Set flow component info in context."""
    _flow_context.set(component_info)
    logger.debug(f"[FC] Set flow context for user {user_id}")


async def cache_flow_validation(
    flow_id: str, component_info: FlowComponentInfo
) -> None:
    """Cache flow validation results."""
    async with _cache_lock:
        _validation_cache[flow_id] = component_info
        logger.debug(f"[FC] Cached validation for flow {flow_id}")


async def get_cached_flow_validation(flow_id: str) -> Optional[FlowComponentInfo]:
    """Get cached flow validation results."""
    async with _cache_lock:
        cached = _validation_cache.get(flow_id)
        if cached:
            logger.debug(f"[FC] Using cached validation for flow {flow_id}")
        return cached


def clear_validation_cache():
    """Clear the validation cache (useful for testing or cache invalidation)."""
    global _validation_cache
    _validation_cache.clear()
    logger.debug("[FC] Cleared validation cache")


@contextmanager
def flow_context(component_info: FlowComponentInfo):
    """Context manager for setting flow component info."""
    token = _flow_context.set(component_info)
    try:
        yield
    finally:
        _flow_context.reset(token)
