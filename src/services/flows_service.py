from config.settings import (
    AGENT_COMPONENT_DISPLAY_NAME,
    DISABLE_INGEST_WITH_LANGFLOW,
    LANGFLOW_URL_INGEST_FLOW_ID,
    NUDGES_FLOW_ID,
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
    OPENAI_LLM_COMPONENT_DISPLAY_NAME,
    clients,
    get_openrag_config,
)
import json
import os
from datetime import datetime
from utils.logging_config import get_logger
from utils.telemetry import TelemetryClient, Category, MessageId

logger = get_logger(__name__)


class FlowsService:
    async def resolve_ollama_url(self, endpoint: str, force_refresh: bool = False) -> str:
        """Find the correct Ollama URL by probing candidates via Langflow's validate-provider API."""
        from config.config_manager import config_manager
        config = config_manager.get_config()

        from utils.container_utils import is_localhost_url, replace_localhost_patterns, get_container_host, transform_localhost_url

        # If not forcing, check if we already have a resolved endpoint for this original endpoint
        if not force_refresh and config.providers.ollama.resolved_endpoint:
            # We only use the cached one if the original endpoint is still a localhost one
            if is_localhost_url(endpoint):
                logger.debug(f"Using cached resolved Ollama URL: {config.providers.ollama.resolved_endpoint}")
                return config.providers.ollama.resolved_endpoint

        if not is_localhost_url(endpoint):
            return endpoint

        # Candidates to probe
        candidates = ["host.containers.internal", "host.docker.internal"]
        detected_host = get_container_host()
        if detected_host and detected_host not in candidates:
            candidates.insert(0, detected_host)

        resolved_url = None
        for cand in candidates:
            test_url = replace_localhost_patterns(endpoint, cand)

            logger.debug(f"Probing Ollama candidate via Langflow: {test_url}")
            try:
                response = await clients.langflow_request(
                    "POST", "/api/v1/models/validate-provider",
                    json={"provider": "Ollama", "variables": {"OLLAMA_BASE_URL": test_url}}
                )
                if response.status_code in (200, 201) and response.json().get("valid"):
                    logger.info(f"Resolved Ollama URL via Langflow: {test_url}")
                    resolved_url = test_url
                    break
            except Exception as e:
                logger.debug(f"Probe failed for {test_url}: {e}")
                continue

        if not resolved_url:
            # Fallback to simple transformation if probing fails
            resolved_url = transform_localhost_url(endpoint)

        # Cache the result if it changed
        if resolved_url and resolved_url != config.providers.ollama.resolved_endpoint:
            config.providers.ollama.resolved_endpoint = resolved_url
            config_manager.save_config_file(config)
            logger.debug(f"Saved resolved Ollama URL to config: {resolved_url}")

        return resolved_url

    def __init__(self):
        # Cache for flow file mappings to avoid repeated filesystem scans
        self._flow_file_cache = {}

    def _get_flows_directory(self):
        """Get the flows directory path"""
        from config.paths import get_flows_path
        return get_flows_path()

    def _get_backup_directory(self):
        """Get the backup directory path"""
        from config.paths import get_flows_backup_path
        backup_dir = get_flows_backup_path()
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    def _get_latest_backup_path(self, flow_id: str, flow_type: str):
        """
        Get the path to the latest backup file for a flow.

        Args:
            flow_id: The flow ID
            flow_type: The flow type name

        Returns:
            str: Path to latest backup file, or None if no backup exists
        """
        backup_dir = self._get_backup_directory()

        if not os.path.exists(backup_dir):
            return None

        # Find all backup files for this flow
        backup_files = []
        prefix = f"{flow_type}_"

        try:
            for filename in os.listdir(backup_dir):
                if filename.startswith(prefix) and filename.endswith(".json"):
                    file_path = os.path.join(backup_dir, filename)
                    # Get modification time for sorting
                    mtime = os.path.getmtime(file_path)
                    backup_files.append((mtime, file_path))
        except Exception as e:
            logger.warning(f"Error reading backup directory: {str(e)}")
            return None

        if not backup_files:
            return None

        # Return the most recent backup (highest mtime)
        backup_files.sort(key=lambda x: x[0], reverse=True)
        return backup_files[0][1]

    def _compare_flows(self, flow1: dict, flow2: dict):
        """
        Compare two flow structures to see if they're different.
        Normalizes both flows before comparison.

        Args:
            flow1: First flow data
            flow2: Second flow data

        Returns:
            bool: True if flows are different, False if they're the same
        """
        normalized1 = self._normalize_flow_structure(flow1)
        normalized2 = self._normalize_flow_structure(flow2)

        # Compare normalized structures
        return normalized1 != normalized2

    async def backup_all_flows(self, only_if_changed=True):
        """
        Backup all flows from Langflow to the backup folder.
        Only backs up flows that have changed since the last backup.

        Args:
            only_if_changed: If True, only backup flows that differ from latest backup

        Returns:
            dict: Summary of backup operations with success/failure status
        """
        backup_results = {
            "success": True,
            "backed_up": [],
            "skipped": [],
            "failed": [],
        }

        flow_configs = [
            ("nudges", NUDGES_FLOW_ID),
            ("retrieval", LANGFLOW_CHAT_FLOW_ID),
            ("ingest", LANGFLOW_INGEST_FLOW_ID),
            ("url_ingest", LANGFLOW_URL_INGEST_FLOW_ID),
        ]

        logger.info("Starting periodic backup of Langflow flows")

        for flow_type, flow_id in flow_configs:
            if not flow_id:
                continue

            try:
                # Get current flow from Langflow
                response = await clients.langflow_request("GET", f"/api/v1/flows/{flow_id}")
                if response.status_code != 200:
                    logger.warning(
                        f"Failed to get flow {flow_id} for backup: HTTP {response.status_code}"
                    )
                    backup_results["failed"].append({
                        "flow_type": flow_type,
                        "flow_id": flow_id,
                        "error": f"HTTP {response.status_code}",
                    })
                    backup_results["success"] = False
                    continue

                current_flow = response.json()

                # Check if flow is locked and if we should skip backup
                flow_locked = current_flow.get("locked", False)
                latest_backup_path = self._get_latest_backup_path(flow_id, flow_type)
                has_backups = latest_backup_path is not None

                # If flow is locked and no backups exist, skip backup
                if flow_locked and not has_backups:
                    logger.debug(
                        f"Flow {flow_type} (ID: {flow_id}) is locked and has no backups, skipping backup"
                    )
                    backup_results["skipped"].append({
                        "flow_type": flow_type,
                        "flow_id": flow_id,
                        "reason": "locked_without_backups",
                    })
                    continue

                # Check if we need to backup (only if changed)
                if only_if_changed and has_backups:
                    try:
                        with open(latest_backup_path, "r") as f:
                            latest_backup = json.load(f)

                        # Compare flows
                        if not self._compare_flows(current_flow, latest_backup):
                            logger.debug(
                                f"Flow {flow_type} (ID: {flow_id}) unchanged, skipping backup"
                            )
                            backup_results["skipped"].append({
                                "flow_type": flow_type,
                                "flow_id": flow_id,
                                "reason": "unchanged",
                            })
                            continue
                    except Exception as e:
                        logger.warning(
                            f"Failed to read latest backup for {flow_type} (ID: {flow_id}): {str(e)}"
                        )
                        # Continue with backup if we can't read the latest backup

                # Backup the flow
                backup_path = await self._backup_flow(flow_id, flow_type, current_flow)
                if backup_path:
                    backup_results["backed_up"].append({
                        "flow_type": flow_type,
                        "flow_id": flow_id,
                        "backup_path": backup_path,
                    })
                else:
                    backup_results["failed"].append({
                        "flow_type": flow_type,
                        "flow_id": flow_id,
                        "error": "Backup returned None",
                    })
                    backup_results["success"] = False
            except Exception as e:
                logger.error(
                    f"Failed to backup {flow_type} flow (ID: {flow_id}): {str(e)}"
                )
                backup_results["failed"].append({
                    "flow_type": flow_type,
                    "flow_id": flow_id,
                    "error": str(e),
                })
                backup_results["success"] = False

        logger.info(
            "Completed periodic backup of flows",
            backed_up_count=len(backup_results["backed_up"]),
            skipped_count=len(backup_results["skipped"]),
            failed_count=len(backup_results["failed"]),
        )

        # Send telemetry event
        if backup_results["failed"]:
            await TelemetryClient.send_event(Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_BACKUP_FAILED)
        else:
            await TelemetryClient.send_event(Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_BACKUP_COMPLETE)

        return backup_results

    async def _backup_flow(self, flow_id: str, flow_type: str, flow_data: dict = None):
        """
        Backup a single flow to the backup folder.

        Args:
            flow_id: The flow ID to backup
            flow_type: The flow type name (nudges, retrieval, ingest, url_ingest)
            flow_data: The flow data to backup (if None, fetches from API)

        Returns:
            str: Path to the backup file, or None if backup failed
        """
        try:
            # Get flow data if not provided
            if flow_data is None:
                response = await clients.langflow_request("GET", f"/api/v1/flows/{flow_id}")
                if response.status_code != 200:
                    logger.warning(
                        f"Failed to get flow {flow_id} for backup: HTTP {response.status_code}"
                    )
                    return None
                flow_data = response.json()

            # Create backup directory if it doesn't exist
            backup_dir = self._get_backup_directory()

            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"{flow_type}_{timestamp}.json"
            backup_path = os.path.join(backup_dir, backup_filename)

            # Save flow to backup file
            with open(backup_path, "w") as f:
                json.dump(flow_data, f, indent=2, ensure_ascii=False)

            logger.info(
                f"Backed up {flow_type} flow (ID: {flow_id}) to {backup_filename}",
                backup_path=backup_path,
            )

            return backup_path

        except Exception as e:
            logger.error(
                f"Failed to backup flow {flow_id} ({flow_type}): {str(e)}",
                error=str(e),
            )
            return None

    def _find_flow_file_by_id(self, flow_id: str):
        """
        Scan the flows directory and find the JSON file that contains the specified flow ID.

        Args:
            flow_id: The flow ID to search for

        Returns:
            str: The path to the flow file, or None if not found
        """
        if not flow_id:
            raise ValueError("flow_id is required")

        # Check cache first
        if flow_id in self._flow_file_cache:
            cached_path = self._flow_file_cache[flow_id]
            if os.path.exists(cached_path):
                return cached_path
            else:
                # Remove stale cache entry
                del self._flow_file_cache[flow_id]

        flows_dir = self._get_flows_directory()

        if not os.path.exists(flows_dir):
            logger.warning(f"Flows directory not found: {flows_dir}")
            return None

        # Scan all JSON files in the flows directory
        try:
            for filename in os.listdir(flows_dir):
                if not filename.endswith(".json"):
                    continue

                file_path = os.path.join(flows_dir, filename)

                try:
                    with open(file_path, "r") as f:
                        flow_data = json.load(f)

                    # Check if this file contains the flow we're looking for
                    if flow_data.get("id") == flow_id:
                        # Cache the result
                        self._flow_file_cache[flow_id] = file_path
                        logger.info(f"Found flow {flow_id} in file: {filename}")
                        return file_path

                except (json.JSONDecodeError, FileNotFoundError) as e:
                    logger.warning(f"Error reading flow file {filename}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error scanning flows directory: {e}")
            return None

        logger.warning(f"Flow with ID {flow_id} not found in flows directory")
        return None

    async def reset_langflow_flow(self, flow_type: str):
        """Reset a Langflow flow by uploading the corresponding JSON file

        Args:
            flow_type: Either 'nudges', 'retrieval', or 'ingest'

        Returns:
            dict: Success/error response
        """
        if not LANGFLOW_URL:
            raise ValueError("LANGFLOW_URL environment variable is required")

        # Determine flow ID based on type
        if flow_type == "nudges":
            flow_id = NUDGES_FLOW_ID
        elif flow_type == "retrieval":
            flow_id = LANGFLOW_CHAT_FLOW_ID
        elif flow_type == "ingest":
            flow_id = LANGFLOW_INGEST_FLOW_ID
        elif flow_type == "url_ingest":
            flow_id = LANGFLOW_URL_INGEST_FLOW_ID
        else:
            raise ValueError(
                "flow_type must be either 'nudges', 'retrieval', 'ingest', or 'url_ingest'"
            )

        if not flow_id:
            raise ValueError(f"Flow ID not configured for flow_type '{flow_type}'")

        # Dynamically find the flow file by ID
        flow_path = self._find_flow_file_by_id(flow_id)
        if not flow_path:
            raise FileNotFoundError(f"Flow file not found for flow ID: {flow_id}")

        # Load flow JSON file
        try:
            with open(flow_path, "r") as f:
                flow_data = json.load(f)
            logger.info(
                f"Successfully loaded flow data for {flow_type} from {os.path.basename(flow_path)}"
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in flow file {flow_path}: {e}")
        except FileNotFoundError:
            raise ValueError(f"Flow file not found: {flow_path}")

        # Make PATCH request to Langflow API to update the flow using shared client
        try:
            response = await clients.langflow_request(
                "PATCH", f"/api/v1/flows/{flow_id}", json=flow_data
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(
                    f"Successfully reset {flow_type} flow",
                    flow_id=flow_id,
                    flow_file=os.path.basename(flow_path),
                )

                # Now update the flow with current configuration settings
                try:
                    config = get_openrag_config()

                    # Check if configuration has been edited (onboarding completed)
                    if config.edited:
                        logger.info(
                            f"Updating {flow_type} flow with current configuration settings"
                        )

                        # Update current LLM provider
                        update_result = await self._update_provider_components(
                            {"name": flow_type, "flow_id": flow_id},
                            config.agent.llm_provider.lower(),
                            llm_model=config.agent.llm_model,
                            force_llm_update=True
                        )

                        # Update all configured embedding providers
                        embedding_providers = []
                        if config.providers.openai.configured:
                            embedding_providers.append("openai")
                        if config.providers.watsonx.configured:
                            embedding_providers.append("watsonx")
                        if config.providers.ollama.configured:
                            embedding_providers.append("ollama")

                        current_emb_provider = config.knowledge.embedding_provider.lower()
                        for provider in embedding_providers:
                            model = config.knowledge.embedding_model if provider == current_emb_provider else None
                            await self._update_provider_components(
                                {"name": flow_type, "flow_id": flow_id},
                                provider,
                                embedding_model=model,
                                force_embedding_update=True
                            )

                        if update_result.get("success"):
                            logger.info(
                                f"Successfully updated {flow_type} flow with current configuration"
                            )
                        else:
                            logger.warning(
                                f"Failed to update {flow_type} flow with current configuration: {update_result.get('error', 'Unknown error')}"
                            )
                    else:
                        logger.info(
                            f"Configuration not yet edited (onboarding not completed), skipping model updates for {flow_type} flow"
                        )

                except Exception as e:
                    logger.error(
                        f"Error updating {flow_type} flow with current configuration",
                        error=str(e),
                    )
                    # Don't fail the entire reset operation if configuration update fails

                return {
                    "success": True,
                    "message": f"Successfully reset {flow_type} flow",
                    "flow_id": flow_id,
                    "flow_type": flow_type,
                }
            else:
                error_text = response.text
                logger.error(
                    f"Failed to reset {flow_type} flow",
                    status_code=response.status_code,
                    error=error_text,
                )
                return {
                    "success": False,
                    "error": f"Failed to reset flow: HTTP {response.status_code} - {error_text}",
                }
        except Exception as e:
            logger.error(f"Error while resetting {flow_type} flow", error=str(e))
            return {"success": False, "error": f"Error: {str(e)}"}

    def _find_node_in_flow(self, flow_data, node_id=None, display_name=None):
        """
        Helper function to find a node in flow data by ID or display name.
        Returns tuple of (node, node_index) or (None, None) if not found.
        """
        nodes = flow_data.get("data", {}).get("nodes", [])

        for i, node in enumerate(nodes):
            node_data = node.get("data", {})
            node_template = node_data.get("node", {})

            # Check by ID if provided
            if node_id and node_data.get("id") == node_id:
                return node, i

            # Check by display_name if provided
            if display_name and node_template.get("display_name") == display_name:
                return node, i

        return None, None

    def _find_nodes_in_flow(self, flow_data, display_name=None):
        """Find all nodes in flow data by display name."""
        nodes = flow_data.get("data", {}).get("nodes", [])
        found = []
        for i, node in enumerate(nodes):
            node_data = node.get("data", {})
            node_template = node_data.get("node", {})
            if display_name and node_template.get("display_name") == display_name:
                found.append((node, i))
        return found

    def _get_node_provider(self, node):
        """Get the provider name currently set in a node."""
        template = node.get("data", {}).get("node", {}).get("template", {})
        model_val = template.get("model", {}).get("value")
        if isinstance(model_val, list) and len(model_val) > 0:
            return model_val[0].get("provider")
        return None

    def _get_provider_name_display(self, provider: str):
        if provider == "watsonx":
            return "IBM WatsonX"
        if provider == "ollama":
            return "Ollama"
        if provider == "anthropic":
            return "Anthropic"
        return "OpenAI"

    async def _update_flow_field(self, flow_id: str, field_name: str, field_value: str, node_display_name: str = None):
        """
        Generic helper function to update any field in any Langflow component.

        Args:
            flow_id: The ID of the flow to update
            field_name: The name of the field to update (e.g., 'model_name', 'system_message', 'docling_serve_opts')
            field_value: The new value to set
            node_display_name: The display name to search for (optional)
            node_id: The node ID to search for (optional, used as fallback or primary)
        """
        if not flow_id:
            raise ValueError("flow_id is required")

        # Get the current flow data from Langflow
        response = await clients.langflow_request("GET", f"/api/v1/flows/{flow_id}")

        if response.status_code != 200:
            raise Exception(
                f"Failed to get flow: HTTP {response.status_code} - {response.text}"
            )

        flow_data = response.json()

        # Find the target component by display name first, then by ID as fallback
        target_node, target_node_index = None, None
        if node_display_name:
            target_node, target_node_index = self._find_node_in_flow(
                flow_data, display_name=node_display_name
            )

        if target_node is None:
            identifier = node_display_name
            raise Exception(f"Component '{identifier}' not found in flow {flow_id}")

        # Update the field value directly in the existing node
        template = target_node.get("data", {}).get("node", {}).get("template", {})
        if template.get(field_name):
            flow_data["data"]["nodes"][target_node_index]["data"]["node"]["template"][field_name]["value"] = field_value
            if "options" in flow_data["data"]["nodes"][target_node_index]["data"]["node"]["template"][field_name] and field_value not in flow_data["data"]["nodes"][target_node_index]["data"]["node"]["template"][field_name]["options"]:
                flow_data["data"]["nodes"][target_node_index]["data"]["node"]["template"][field_name]["options"].append(field_value)
        else:
            identifier = node_display_name
            raise Exception(f"{field_name} field not found in {identifier} component")

        # Update the flow via PATCH request
        patch_response = await clients.langflow_request(
            "PATCH", f"/api/v1/flows/{flow_id}", json=flow_data
        )

        if patch_response.status_code != 200:
            raise Exception(
                f"Failed to update flow: HTTP {patch_response.status_code} - {patch_response.text}"
            )

    async def update_chat_flow_model(self, model_name: str, provider: str):
        """Helper function to update the model in the chat flow"""
        if not LANGFLOW_CHAT_FLOW_ID:
            raise ValueError("LANGFLOW_CHAT_FLOW_ID is not configured")

        # Determine target component IDs based on provider
        target_llm_id = self._get_provider_component_ids(provider)[1]

        await self._update_flow_field(LANGFLOW_CHAT_FLOW_ID, "model_name", model_name,
                                node_display_name=target_llm_id)

    async def update_chat_flow_system_prompt(self, system_prompt: str, provider: str):
        """Helper function to update the system prompt in the chat flow"""
        if not LANGFLOW_CHAT_FLOW_ID:
            raise ValueError("LANGFLOW_CHAT_FLOW_ID is not configured")

        # Determine target component IDs based on provider
        target_agent_id = self._get_provider_component_ids(provider)[1]

        await self._update_flow_field(LANGFLOW_CHAT_FLOW_ID, "system_prompt", system_prompt,
                                node_display_name=target_agent_id)

    async def update_flow_docling_preset(self, preset: str, preset_config: dict):
        """Helper function to update docling preset in the ingest flow"""
        if not LANGFLOW_INGEST_FLOW_ID:
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        from config.settings import DOCLING_COMPONENT_DISPLAY_NAME
        await self._update_flow_field(LANGFLOW_INGEST_FLOW_ID, "docling_serve_opts", preset_config,
                                node_display_name=DOCLING_COMPONENT_DISPLAY_NAME)

    async def update_ingest_flow_chunk_size(self, chunk_size: int):
        """Helper function to update chunk size in the ingest flow"""
        if not LANGFLOW_INGEST_FLOW_ID:
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")
        await self._update_flow_field(
            LANGFLOW_INGEST_FLOW_ID,
            "chunk_size",
            chunk_size,
            node_display_name="Split Text",
        )

    async def update_ingest_flow_chunk_overlap(self, chunk_overlap: int):
        """Helper function to update chunk overlap in the ingest flow"""
        if not LANGFLOW_INGEST_FLOW_ID:
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")
        await self._update_flow_field(
            LANGFLOW_INGEST_FLOW_ID,
            "chunk_overlap",
            chunk_overlap,
            node_display_name="Split Text",
        )

    async def update_ingest_flow_embedding_model(self, embedding_model: str, provider: str):
        """Helper function to update embedding model in the ingest flow"""
        if not LANGFLOW_INGEST_FLOW_ID:
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        # Determine target component IDs based on provider
        target_embedding_id = self._get_provider_component_ids(provider)[0]

        await self._update_flow_field(LANGFLOW_INGEST_FLOW_ID, "model", embedding_model,
                                node_display_name=target_embedding_id)

    def _replace_node_in_flow(self, flow_data, old_display_name, new_node):
        """Replace a node in the flow data"""
        nodes = flow_data.get("data", {}).get("nodes", [])
        for i, node in enumerate(nodes):
            if node.get("data", {}).get("node", {}).get("display_name") == old_display_name:
                nodes[i] = new_node
                return True
        return False

    def _normalize_flow_structure(self, flow_data):
        """
        Normalize flow structure for comparison by removing dynamic fields.
        Keeps structural elements: nodes (types, display names, templates), edges (connections).
        Removes: IDs, timestamps, positions, etc. but keeps template structure.
        """
        normalized = {
            "data": {
                "nodes": [],
                "edges": []
            }
        }

        # Normalize nodes - keep structural info including templates
        nodes = flow_data.get("data", {}).get("nodes", [])
        for node in nodes:
            node_data = node.get("data", {})
            node_template = node_data.get("node", {})

            normalized_node = {
                "id": node.get("id"),  # Keep ID for edge matching
                "type": node.get("type"),
                "data": {
                    "node": {
                        "display_name": node_template.get("display_name"),
                        "name": node_template.get("name"),
                        "base_classes": node_template.get("base_classes", []),
                        "template": node_template.get("template", {}),  # Include template structure
                    }
                }
            }
            normalized["data"]["nodes"].append(normalized_node)

        # Normalize edges - keep only connections
        edges = flow_data.get("data", {}).get("edges", [])
        for edge in edges:
            normalized_edge = {
                "source": edge.get("source"),
                "target": edge.get("target"),
                "sourceHandle": edge.get("sourceHandle"),
                "targetHandle": edge.get("targetHandle"),
            }
            normalized["data"]["edges"].append(normalized_edge)

        return normalized

    async def _compare_flow_with_file(self, flow_id: str):
        """
        Compare a Langflow flow with its JSON file.
        Returns True if flows match (indicating a reset), False otherwise.
        """
        try:
            # Get flow from Langflow API
            response = await clients.langflow_request("GET", f"/api/v1/flows/{flow_id}")
            if response.status_code != 200:
                logger.warning(f"Failed to get flow {flow_id} from Langflow: HTTP {response.status_code}")
                return False

            langflow_flow = response.json()

            # Find and load the corresponding JSON file
            flow_path = self._find_flow_file_by_id(flow_id)
            if not flow_path:
                logger.warning(f"Flow file not found for flow ID: {flow_id}")
                return False

            with open(flow_path, "r") as f:
                file_flow = json.load(f)

            # Normalize both flows for comparison
            normalized_langflow = self._normalize_flow_structure(langflow_flow)
            normalized_file = self._normalize_flow_structure(file_flow)

            # Compare entire normalized structures exactly
            # Sort nodes and edges for consistent comparison
            normalized_langflow["data"]["nodes"] = sorted(
                normalized_langflow["data"]["nodes"],
                key=lambda x: (x.get("id", ""), x.get("type", ""))
            )
            normalized_file["data"]["nodes"] = sorted(
                normalized_file["data"]["nodes"],
                key=lambda x: (x.get("id", ""), x.get("type", ""))
            )

            normalized_langflow["data"]["edges"] = sorted(
                normalized_langflow["data"]["edges"],
                key=lambda x: (x.get("source", ""), x.get("target", ""), x.get("sourceHandle", ""), x.get("targetHandle", ""))
            )
            normalized_file["data"]["edges"] = sorted(
                normalized_file["data"]["edges"],
                key=lambda x: (x.get("source", ""), x.get("target", ""), x.get("sourceHandle", ""), x.get("targetHandle", ""))
            )

            # Compare entire normalized structures
            return normalized_langflow == normalized_file

        except Exception as e:
            logger.error(f"Error comparing flow {flow_id} with file: {str(e)}")
            return False

    async def ensure_flows_exist(self) -> set[str]:
        """
        Ensure all configured flows exist in Langflow.

        Creates flows from their JSON files if they are not already present in
        the Langflow database.  This is intentionally create-only: it never
        patches or overwrites an existing flow, preserving any edits the user
        has made in the Langflow UI.

        This replaces the LANGFLOW_LOAD_FLOWS_PATH mechanism, which performed a
        blind upsert on every container start and discarded user edits.

        Returns the set of flow type names that were actually created.
        """
        flow_configs = [
            ("nudges", NUDGES_FLOW_ID),
            ("retrieval", LANGFLOW_CHAT_FLOW_ID),
            ("ingest", LANGFLOW_INGEST_FLOW_ID),
            ("url_ingest", LANGFLOW_URL_INGEST_FLOW_ID),
        ]
        created_flow_types: set[str] = set()

        for flow_type, flow_id in flow_configs:
            if not flow_id:
                continue

            try:
                response = await clients.langflow_request(
                    "GET", f"/api/v1/flows/{flow_id}"
                )
                if response.status_code == 200:
                    logger.info(
                        f"Flow {flow_type} (ID: {flow_id}) already exists, skipping creation"
                    )
                    continue

                if response.status_code != 404:
                    logger.warning(
                        f"Unexpected status checking {flow_type} flow (ID: {flow_id}): "
                        f"HTTP {response.status_code} — skipping creation to avoid overwriting existing data"
                    )
                    continue

                flow_path = self._find_flow_file_by_id(flow_id)
                if not flow_path:
                    logger.warning(
                        f"No flow file found for {flow_type} (ID: {flow_id}), cannot create"
                    )
                    continue

                with open(flow_path, "r") as f:
                    flow_data = json.load(f)

                response = await clients.langflow_request(
                    "PUT", f"/api/v1/flows/{flow_id}", json=flow_data
                )
                if response.status_code in (200, 201):
                    logger.info(
                        f"Created {flow_type} flow (ID: {flow_id}) from {os.path.basename(flow_path)}"
                    )
                    created_flow_types.add(flow_type)
                else:
                    logger.warning(
                        f"Failed to create {flow_type} flow (ID: {flow_id}): "
                        f"HTTP {response.status_code} — {response.text}"
                    )

            except Exception as e:
                logger.error(
                    f"Error ensuring {flow_type} flow (ID: {flow_id}) exists: {e}"
                )

        return created_flow_types

    async def check_flows_reset(self):
        """
        Check if any flows have been reset by comparing with JSON files.
        Returns list of flow types that were reset.
        """
        reset_flows = []

        flow_configs = [
            ("nudges", NUDGES_FLOW_ID),
            ("retrieval", LANGFLOW_CHAT_FLOW_ID),
            ("ingest", LANGFLOW_INGEST_FLOW_ID),
            ("url_ingest", LANGFLOW_URL_INGEST_FLOW_ID),
        ]

        for flow_type, flow_id in flow_configs:
            if not flow_id:
                continue

            logger.info(f"Checking if {flow_type} flow (ID: {flow_id}) was reset")
            is_reset = await self._compare_flow_with_file(flow_id)

            if is_reset:
                logger.info(f"Flow {flow_type} (ID: {flow_id}) appears to have been reset")
                reset_flows.append(flow_type)
            else:
                logger.info(f"Flow {flow_type} (ID: {flow_id}) does not match reset state")

        return reset_flows

    async def change_langflow_model_value(
        self,
        provider: str,
        embedding_model: str = None,
        llm_model: str = None,
        force_embedding_update: bool = False,
        force_llm_update: bool = False,
        flow_configs: list = None,
    ):
        """
        Change dropdown values for provider-specific components across flows

        Args:
            provider: The provider ("watsonx", "ollama", "openai", "anthropic")
            embedding_model: The embedding model name to set
            llm_model: The LLM model name to set
            force_embedding_update: If True, update embeddings even if model is None
            force_llm_update: If True, update LLM even if model is None
            flow_configs: Optional list of flow configs to update
        """
        if provider not in ["watsonx", "ollama", "openai", "anthropic"]:
            raise ValueError("provider must be 'watsonx', 'ollama', 'openai', or 'anthropic'")

        try:
            # Use provided flow_configs or default to all flows
            if flow_configs is None:
                flow_configs = [
                    {"name": "nudges", "flow_id": NUDGES_FLOW_ID},
                    {"name": "retrieval", "flow_id": LANGFLOW_CHAT_FLOW_ID},
                    {"name": "ingest", "flow_id": LANGFLOW_INGEST_FLOW_ID},
                    {"name": "url_ingest", "flow_id": LANGFLOW_URL_INGEST_FLOW_ID},
                ]

            results = []
            for config in flow_configs:
                try:
                    result = await self._update_provider_components(
                        config,
                        provider,
                        embedding_model=embedding_model,
                        llm_model=llm_model,
                        force_embedding_update=force_embedding_update,
                        force_llm_update=force_llm_update,
                    )
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error updating {config['name']} flow: {str(e)}")
                    results.append({"flow": config["name"], "success": False, "error": str(e)})

            return {
                "success": all(r.get("success", False) for r in results),
                "results": results,
            }
        except Exception as e:
            logger.error(f"Error in change_langflow_model_value: {str(e)}")
            return {"success": False, "error": str(e)}



    async def _update_provider_components(
        self,
        config,
        provider: str,
        embedding_model: str = None,
        llm_model: str = None,
        force_embedding_update: bool = False,
        force_llm_update: bool = False,
    ):
        """Update provider components and their dropdown values in a flow"""
        flow_name = config["name"]
        flow_id = config["flow_id"]

        # Get flow data from Langflow API instead of file
        response = await clients.langflow_request("GET", f"/api/v1/flows/{flow_id}")

        if response.status_code != 200:
            raise Exception(
                f"Failed to get flow from Langflow: HTTP {response.status_code} - {response.text}"
            )

        flow_data = response.json()

        updates_made = []

        # Update embedding component
        if not DISABLE_INGEST_WITH_LANGFLOW and (embedding_model or force_embedding_update):
            # Get all embedding nodes in the flow
            embedding_nodes = self._find_nodes_in_flow(flow_data, display_name=OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME)
            logger.info(f"Found {len(embedding_nodes)} embedding nodes in flow {flow_name} with display name '{OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME}'")

            # Count configured embedding-enabled providers
            config_obj = get_openrag_config()
            configured_providers = []
            if config_obj.providers.openai.configured: configured_providers.append("openai")
            if config_obj.providers.watsonx.configured: configured_providers.append("watsonx")
            if config_obj.providers.ollama.configured: configured_providers.append("ollama")

            # Ensure current provider is in the list for counting purposes if it's being configured
            if provider in ["openai", "watsonx", "ollama"] and provider not in configured_providers:
                configured_providers.append(provider)

            all_possible = ["openai", "watsonx", "ollama"]
            configured_providers = [p for p in all_possible if p in configured_providers]
            provider_count = len(configured_providers)
            logger.info(f"Configured embedding providers: {configured_providers} (count: {provider_count})")

            # Determine slot mapping context
            if provider_count == 1:
                logger.info("Configuration mode: all 3 slots belong to the single active provider")
            elif provider_count == 2:
                logger.info("Configuration mode: first 2 slots assigned to providers 1 and 2")
            elif provider_count == 3:
                logger.info("Configuration mode: slots 1, 2, and 3 assigned to their respective providers")

            # 1. Check if any node is already this provider - always update those first
            matched_nodes = []
            provider_display = self._get_provider_name_display(provider)
            for node, idx in embedding_nodes:
                if self._get_node_provider(node) == provider_display:
                    matched_nodes.append((node, idx))

            if matched_nodes:
                logger.info(f"Found {len(matched_nodes)} nodes already configured for provider '{provider}'")
                for node, idx in matched_nodes:
                    if await self._update_component_fields(node, provider, embedding_model):
                        updates_made.append(f"embedding model: {embedding_model} (updated existing {provider} node)")
            else:
                # 2. No existing node matched, use slot-based logic
                try:
                    p_index = configured_providers.index(provider)
                    logger.info(f"Using slot-based logic for provider '{provider}' (p_index: {p_index}, total configured: {provider_count})")

                    if provider_count == 1:
                        # Single provider mode: update all available nodes (up to 3)
                        logger.info(f"Single provider mode: updating all available embedding nodes (available: {len(embedding_nodes)})")
                        for i in range(min(3, len(embedding_nodes))):
                            node, idx = embedding_nodes[i]
                            if await self._update_component_fields(node, provider, embedding_model):
                                updates_made.append(
                                    f"embedding model: {embedding_model} (set node {i+1})"
                                )
                    else:
                        # Multiple providers: each gets one slot based on its list index
                        # This satisfies:
                        # - 2 providers -> node 0 and node 1 updated ("two first nodes")
                        # - 3 providers -> node 0, 1, 2 updated ("each gets its first one")
                        if p_index < len(embedding_nodes):
                            node, idx = embedding_nodes[p_index]
                            logger.info(f"Multiple provider mode: assigning provider '{provider}' to node slot {p_index} (node {p_index+1})")
                            if await self._update_component_fields(node, provider, embedding_model):
                                updates_made.append(
                                    f"embedding model: {embedding_model} (set node {p_index+1})"
                                )
                        else:
                            logger.info(f"Provider index {p_index} exceeds available embedding nodes ({len(embedding_nodes)}) - skipping automatic assignment")
                except ValueError:
                    logger.warning(f"Current provider '{provider}' not found in configured providers list: {configured_providers}")

        # Update LLM component (if exists in this flow)
        if llm_model or force_llm_update:
            llm_node, _ = self._find_node_in_flow(flow_data, display_name=OPENAI_LLM_COMPONENT_DISPLAY_NAME)
            if llm_node:
                if await self._update_component_fields(
                    llm_node, provider, llm_model
                ):
                    updates_made.append(f"llm model: {llm_model}")
            # Update LLM component (if exists in this flow)
            agent_node, _ = self._find_node_in_flow(flow_data, display_name=AGENT_COMPONENT_DISPLAY_NAME)
            if agent_node:
                if await self._update_component_fields(
                    agent_node, provider, llm_model
                ):
                    updates_made.append(f"agent model: {llm_model}")

        # If no updates were made, return skip message
        if not updates_made:
            return {
                "flow": flow_name,
                "success": True,
                "message": f"No compatible components found in {flow_name} flow (skipped)",
                "flow_id": flow_id,
            }

        logger.info(f"Updated {', '.join(updates_made)} in {flow_name} flow")

        # PATCH the updated flow
        response = await clients.langflow_request(
            "PATCH", f"/api/v1/flows/{flow_id}", json=flow_data
        )

        if response.status_code != 200:
            raise Exception(
                f"Failed to update flow: HTTP {response.status_code} - {response.text}"
            )

        return {
            "flow": flow_name,
            "success": True,
            "message": f"Successfully updated {', '.join(updates_made)}",
            "flow_id": flow_id,
        }

    async def _update_component_langflow(self, template, model: str):
        # Call custom_component/update endpoint to get updated template
        # Only call if code field exists (custom components should have code)
        if "code" in template and "value" in template["code"]:
            code_value = template["code"]["value"]

            try:
                update_payload = {
                    "code": code_value,
                    "template": template,
                    "field": "model",
                    "field_value": model,
                    "tool_mode": False,
                }

                response = await clients.langflow_request(
                    "POST", "/api/v1/custom_component/update", json=update_payload
                )

                if response.status_code == 200:
                    response_data = response.json()
                    # Update template with the new template from response.data
                    if "template" in response_data:
                        # Update the template in component_node
                        return response_data["template"]
                    else:
                        logger.warning("Response from custom_component/update missing 'data' field")
                else:
                    logger.warning(
                        f"Failed to call custom_component/update: HTTP {response.status_code} - {response.text}"
                    )
            except Exception as e:
                logger.error(f"Error calling custom_component/update: {str(e)}")
                # Continue with manual updates even if API call fails

    async def _update_component_fields(
        self,
        component_node,
        provider: str,
        model_value: str,
    ):
        """Update fields in a component node based on provider and component type"""
        template = component_node.get("data", {}).get("node", {}).get("template", {})
        if not template:
            return False

        updated = False
        provider_name = self._get_provider_name_display(provider)

        # Enable the model in Langflow first
        await self._enable_model_in_langflow(provider_name, model_value)

        # Update model field and call custom_component/update endpoint
        if "model" in template:
            if "options" not in template["model"]:
                return False

            # Update template via Langflow API to get latest options
            template = await self._update_component_langflow(template, template["model"]["value"]) or template
            component_node["data"]["node"]["template"] = template

            # Find the specific model option for the provider
            if model_value:
                model_options = [
                    item for item in template["model"].get("options", [])
                    if item.get("provider") == provider_name and item.get("name") == model_value
                ]
            else:
                # If no specific model provided, pick the first available one for this provider
                model_options = [
                    item for item in template["model"].get("options", [])
                    if item.get("provider") == provider_name
                ][:1]
                if model_options:
                    logger.info(f"Using first available model '{model_options[0].get('name')}' for provider {provider_name}")

            if not model_options:
                logger.warning(f"Model {model_value or 'ANY'} not found for provider {provider_name}")
                return False

            template["model"]["value"] = model_options

            template = await self._update_component_langflow(template, model_options) or template
            component_node["data"]["node"]["template"] = template

            updated = True

        # Update provider-specific fields using Langflow global variable names.
        # "api_base" is the Ollama URL field on the Embedding Model component;
        # "ollama_base_url" is the equivalent field on the Language Model / Agent component.
        field_mappings = {
            "api_key": {
                "openai": "OPENAI_API_KEY",
                "watsonx": "WATSONX_APIKEY",
                "anthropic": "ANTHROPIC_API_KEY",
            },
            "api_base": {
                "ollama": "OLLAMA_BASE_URL",
            },
            "ollama_base_url": {
                "ollama": "OLLAMA_BASE_URL",
            },
            "base_url_ibm_watsonx": {
                "watsonx": "WATSONX_URL",
            },
            "project_id": {
                "watsonx": "WATSONX_PROJECT_ID",
            },
        }

        for field, mapping in field_mappings.items():
            if field in template:
                target_value = mapping.get(provider)
                if target_value:
                    template[field]["value"] = target_value
                    template[field]["load_from_db"] = True
                else:
                    template[field]["value"] = ""
                    template[field]["load_from_db"] = False
                updated = True

        return updated

    async def _enable_model_in_langflow(self, provider_name: str, model_value: str):
        """Ensure the specified model is enabled in Langflow."""
        try:
            enable_payload = [{
                "provider": provider_name,
                "model_id": model_value,
                "enabled": True
            }]

            response = await clients.langflow_request(
                "POST", "/api/v1/models/enabled_models", json=enable_payload
            )

            if response.status_code == 200:
                logger.info(f"Successfully enabled model {model_value} for provider {provider_name}")
            else:
                logger.warning(
                    f"Failed to enable model: HTTP {response.status_code} - {response.text}"
                )
        except Exception as e:
            logger.error(f"Error enabling model {model_value}: {str(e)}")

    def _get_provider_component_ids(self, provider: str):
        """Helper to get component display names for various providers."""
        from config.settings import (
            OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
            OPENAI_LLM_COMPONENT_DISPLAY_NAME,
            WATSONX_EMBEDDING_COMPONENT_DISPLAY_NAME,
            WATSONX_LLM_COMPONENT_DISPLAY_NAME,
            OLLAMA_EMBEDDING_COMPONENT_DISPLAY_NAME,
            OLLAMA_LLM_COMPONENT_DISPLAY_NAME,
        )
        if provider == "openai":
            return (OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME, OPENAI_LLM_COMPONENT_DISPLAY_NAME)
        elif provider == "watsonx":
            return (WATSONX_EMBEDDING_COMPONENT_DISPLAY_NAME, WATSONX_LLM_COMPONENT_DISPLAY_NAME)
        elif provider == "ollama":
            return (OLLAMA_EMBEDDING_COMPONENT_DISPLAY_NAME, OLLAMA_LLM_COMPONENT_DISPLAY_NAME)
        elif provider == "anthropic":
            return (None, "Anthropic")
        return (None, None)
