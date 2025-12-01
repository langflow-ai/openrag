from config.settings import (
    AGENT_COMPONENT_DISPLAY_NAME,
    DISABLE_INGEST_WITH_LANGFLOW,
    LANGFLOW_URL_INGEST_FLOW_ID,
    NUDGES_FLOW_ID,
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    OLLAMA_LLM_TEXT_COMPONENT_PATH,
    OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
    OPENAI_LLM_COMPONENT_DISPLAY_NAME,
    WATSONX_LLM_TEXT_COMPONENT_PATH,
    clients,
    WATSONX_LLM_COMPONENT_PATH,
    WATSONX_EMBEDDING_COMPONENT_PATH,
    OLLAMA_LLM_COMPONENT_PATH,
    OLLAMA_EMBEDDING_COMPONENT_PATH,
    WATSONX_EMBEDDING_COMPONENT_DISPLAY_NAME,
    WATSONX_LLM_COMPONENT_DISPLAY_NAME,
    OLLAMA_EMBEDDING_COMPONENT_DISPLAY_NAME,
    OLLAMA_LLM_COMPONENT_DISPLAY_NAME,
    get_openrag_config,
)
import json
import os
import re
import copy
from datetime import datetime
from utils.logging_config import get_logger
from utils.container_utils import transform_localhost_url

logger = get_logger(__name__)


class FlowsService:
    def __init__(self):
        # Cache for flow file mappings to avoid repeated filesystem scans
        self._flow_file_cache = {}

    def _get_flows_directory(self):
        """Get the flows directory path"""
        current_file_dir = os.path.dirname(os.path.abspath(__file__))  # src/services/
        src_dir = os.path.dirname(current_file_dir)  # src/
        project_root = os.path.dirname(src_dir)  # project root
        return os.path.join(project_root, "flows")

    def _get_backup_directory(self):
        """Get the backup directory path"""
        flows_dir = self._get_flows_directory()
        backup_dir = os.path.join(flows_dir, "backup")
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

                        # Get LLM provider (used for most flows)
                        llm_provider = config.agent.llm_provider.lower()
                        embedding_provider = config.knowledge.embedding_provider.lower()

                        # Get provider-specific endpoint if needed
                        llm_provider_config = config.get_llm_provider_config()
                        endpoint = getattr(llm_provider_config, "endpoint", None)

                        # Step 2: Update model values for the specific flow being reset
                        single_flow_config = [
                            {
                                "name": flow_type,
                                "flow_id": flow_id,
                            }
                        ]

                        logger.info(f"Updating {flow_type} flow model values")
                        
                        # For retrieval flow: need to update both LLM and embedding (potentially different providers)
                        # For ingest flows: only update embedding
                        # For other flows: only update LLM
                        
                        if flow_type == "retrieval":
                            # Retrieval flow uses both LLM and embedding models
                            # Update LLM first
                            llm_endpoint = getattr(llm_provider_config, "endpoint", None)
                            llm_result = await self.change_langflow_model_value(
                                provider=llm_provider,
                                embedding_model=None,
                                llm_model=config.agent.llm_model,
                                endpoint=llm_endpoint,
                                flow_configs=single_flow_config,
                            )
                            if not llm_result.get("success"):
                                logger.warning(
                                    f"Failed to update LLM in {flow_type} flow: {llm_result.get('error', 'Unknown error')}"
                                )
                            
                            # Update embedding model
                            embedding_provider_config = config.get_embedding_provider_config()
                            embedding_endpoint = getattr(embedding_provider_config, "endpoint", None)
                            embedding_result = await self.change_langflow_model_value(
                                provider=embedding_provider,
                                embedding_model=config.knowledge.embedding_model,
                                llm_model=None,
                                endpoint=embedding_endpoint,
                                flow_configs=single_flow_config,
                            )
                            if not embedding_result.get("success"):
                                logger.warning(
                                    f"Failed to update embedding in {flow_type} flow: {embedding_result.get('error', 'Unknown error')}"
                                )
                            
                            # Consider it successful if either update succeeded
                            update_result = {
                                "success": llm_result.get("success") or embedding_result.get("success"),
                                "llm_result": llm_result,
                                "embedding_result": embedding_result,
                            }
                        elif flow_type in ["ingest", "url_ingest"]:
                            # Ingest flows only need embedding model
                            embedding_provider_config = config.get_embedding_provider_config()
                            embedding_endpoint = getattr(embedding_provider_config, "endpoint", None)
                            update_result = await self.change_langflow_model_value(
                                provider=embedding_provider,
                                embedding_model=config.knowledge.embedding_model,
                                llm_model=None,
                                endpoint=embedding_endpoint,
                                flow_configs=single_flow_config,
                            )
                        else:
                            # Other flows (nudges) only need LLM model
                            llm_endpoint = getattr(llm_provider_config, "endpoint", None)
                            update_result = await self.change_langflow_model_value(
                                provider=llm_provider,
                                embedding_model=None,
                                llm_model=config.agent.llm_model,
                                endpoint=llm_endpoint,
                                flow_configs=single_flow_config,
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

    # async def assign_model_provider(self, provider: str, is_embedding: bool = False):
    #     """
    #     Replace OpenAI components with the specified provider components in all flows

    #     Args:
    #         provider: "watsonx", "ollama", "openai" or "anthropic"

    #     Returns:
    #         dict: Success/error response with details for each flow
    #     """
    #     if provider not in ["watsonx", "ollama", "openai", "anthropic"]:
    #         raise ValueError("provider must be 'watsonx', 'ollama', 'openai', or 'anthropic'")

    #     if provider == "openai":
    #         logger.info("Provider is already OpenAI, no changes needed")
    #         return {
    #             "success": True,
    #             "message": "Provider is already OpenAI, no changes needed",
    #         }

    #     try:
    #         # Load component templates based on provider
    #         llm_template, embedding_template, llm_text_template = (
    #             self._load_component_templates(provider)
    #         )

    #         logger.info(f"Assigning {provider} components")

    #         # Define flow configurations (removed hardcoded file paths)
    #         flow_configs = [
    #             {
    #                 "name": "nudges",
    #                 "flow_id": NUDGES_FLOW_ID,
    #                 "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
    #                 "llm_text_name": OPENAI_LLM_COMPONENT_DISPLAY_NAME,
    #                 "llm_name": None,
    #             },
    #             {
    #                 "name": "retrieval",
    #                 "flow_id": LANGFLOW_CHAT_FLOW_ID,
    #                 "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
    #                 "llm_name": OPENAI_LLM_COMPONENT_DISPLAY_NAME,
    #                 "llm_text_name": None,
    #             },
    #             {
    #                 "name": "ingest",
    #                 "flow_id": LANGFLOW_INGEST_FLOW_ID,
    #                 "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
    #                 "llm_name": None,  # Ingestion flow might not have LLM
    #                 "llm_text_name": None,
    #             },
    #             {
    #                 "name": "url_ingest",
    #                 "flow_id": LANGFLOW_URL_INGEST_FLOW_ID,
    #                 "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
    #                 "llm_name": None,
    #                 "llm_text_name": None,
    #             },
    #         ]

    #         results = []

    #         # Process each flow sequentially
    #         for config in flow_configs:
    #             try:
    #                 result = await self._update_flow_components(
    #                     config, llm_template, embedding_template, llm_text_template, is_embedding
    #                 )
    #                 results.append(result)
    #                 logger.info(f"Successfully updated {config['name']} flow")
    #             except Exception as e:
    #                 error_msg = f"Failed to update {config['name']} flow: {str(e)}"
    #                 logger.error(error_msg)
    #                 results.append(
    #                     {"flow": config["name"], "success": False, "error": error_msg}
    #                 )
    #                 # Continue with other flows even if one fails

    #         # Check if all flows were successful
    #         all_success = all(r.get("success", False) for r in results)

    #         return {
    #             "success": all_success,
    #             "message": f"Model provider assignment to {provider} {'completed' if all_success else 'completed with errors'}",
    #             "provider": provider,
    #             "results": results,
    #         }

    #     except Exception as e:
    #         logger.error(f"Error assigning model provider {provider}", error=str(e))
    #         return {
    #             "success": False,
    #             "error": f"Failed to assign model provider: {str(e)}",
    #         }

    # def _load_component_templates(self, provider: str):
    #     """Load component templates for the specified provider"""
    #     if provider == "watsonx":
    #         llm_path = WATSONX_LLM_COMPONENT_PATH
    #         embedding_path = WATSONX_EMBEDDING_COMPONENT_PATH
    #         llm_text_path = WATSONX_LLM_TEXT_COMPONENT_PATH
    #     elif provider == "ollama":
    #         llm_path = OLLAMA_LLM_COMPONENT_PATH
    #         embedding_path = OLLAMA_EMBEDDING_COMPONENT_PATH
    #         llm_text_path = OLLAMA_LLM_TEXT_COMPONENT_PATH
    #     else:
    #         raise ValueError(f"Unsupported provider: {provider}")

    #     # Get the project root directory (same logic as reset_langflow_flow)
    #     current_file_dir = os.path.dirname(os.path.abspath(__file__))  # src/services/
    #     src_dir = os.path.dirname(current_file_dir)  # src/
    #     project_root = os.path.dirname(src_dir)  # project root

    #     # Load LLM template
    #     llm_full_path = os.path.join(project_root, llm_path)
    #     if not os.path.exists(llm_full_path):
    #         raise FileNotFoundError(
    #             f"LLM component template not found at: {llm_full_path}"
    #         )

    #     with open(llm_full_path, "r") as f:
    #         llm_template = json.load(f)

    #     # Load embedding template
    #     embedding_full_path = os.path.join(project_root, embedding_path)
    #     if not os.path.exists(embedding_full_path):
    #         raise FileNotFoundError(
    #             f"Embedding component template not found at: {embedding_full_path}"
    #         )

    #     with open(embedding_full_path, "r") as f:
    #         embedding_template = json.load(f)

    #     # Load LLM Text template
    #     llm_text_full_path = os.path.join(project_root, llm_text_path)
    #     if not os.path.exists(llm_text_full_path):
    #         raise FileNotFoundError(
    #             f"LLM Text component template not found at: {llm_text_full_path}"
    #         )

    #     with open(llm_text_full_path, "r") as f:
    #         llm_text_template = json.load(f)

    #     logger.info(f"Loaded component templates for {provider}")
    #     return llm_template, embedding_template, llm_text_template

    # async def _update_flow_components(
    #     self, config, llm_template, embedding_template, llm_text_template, is_embedding: bool = False
    # ):
    #     """Update components in a specific flow"""
    #     flow_name = config["name"]
    #     flow_id = config["flow_id"]
    #     old_embedding_name = config["embedding_name"]
    #     old_llm_name = config["llm_name"]
    #     old_llm_text_name = config["llm_text_name"]
    #     # Extract IDs from templates
    #     new_llm_id = llm_template["data"]["id"]
    #     new_embedding_id = embedding_template["data"]["id"]
    #     new_llm_text_id = llm_text_template["data"]["id"]

    #     # Dynamically find the flow file by ID
    #     flow_path = self._find_flow_file_by_id(flow_id)
    #     if not flow_path:
    #         raise FileNotFoundError(f"Flow file not found for flow ID: {flow_id}")

    #     # Load flow JSON
    #     with open(flow_path, "r") as f:
    #         flow_data = json.load(f)

    #     # Find and replace components
    #     components_updated = []

    #     # Replace embedding component
    #     if not DISABLE_INGEST_WITH_LANGFLOW and is_embedding:
    #         embedding_node, _ = self._find_node_in_flow(flow_data, display_name=old_embedding_name)
    #         if embedding_node:
    #             # Preserve position
    #             original_position = embedding_node.get("position", {})

    #             # Replace with new template
    #             new_embedding_node = embedding_template.copy()
    #             new_embedding_node["position"] = original_position

    #             # Replace in flow
    #             self._replace_node_in_flow(flow_data, old_embedding_name, new_embedding_node)
    #             components_updated.append(
    #                 f"embedding: {old_embedding_name} -> {new_embedding_id}"
    #             )

    #     # Replace LLM component (if exists in this flow)
    #     if old_llm_name and not is_embedding:
    #         llm_node, _ = self._find_node_in_flow(flow_data, display_name=old_llm_name)
    #         if llm_node:
    #             # Preserve position
    #             original_position = llm_node.get("position", {})

    #             # Replace with new template
    #             new_llm_node = llm_template.copy()
    #             new_llm_node["position"] = original_position

    #             # Replace in flow
    #             self._replace_node_in_flow(flow_data, old_llm_name, new_llm_node)
    #             components_updated.append(f"llm: {old_llm_name} -> {new_llm_id}")

    #     # Replace LLM component (if exists in this flow)
    #     if old_llm_text_name and not is_embedding:
    #         llm_text_node, _ = self._find_node_in_flow(flow_data, display_name=old_llm_text_name)
    #         if llm_text_node:
    #             # Preserve position
    #             original_position = llm_text_node.get("position", {})

    #             # Replace with new template
    #             new_llm_text_node = llm_text_template.copy()
    #             new_llm_text_node["position"] = original_position

    #             # Replace in flow
    #             self._replace_node_in_flow(flow_data, old_llm_text_name, new_llm_text_node)
    #             components_updated.append(f"llm: {old_llm_text_name} -> {new_llm_text_id}")


    #     old_embedding_id = None
    #     old_llm_id = None
    #     old_llm_text_id = None
    #     if embedding_node:
    #         old_embedding_id = embedding_node.get("data", {}).get("id")
    #     if old_llm_name and llm_node:
    #         old_llm_id = llm_node.get("data", {}).get("id")
    #     if old_llm_text_name and llm_text_node:
    #         old_llm_text_id = llm_text_node.get("data", {}).get("id")

    #     # Update all edge references using regex replacement
    #     flow_json_str = json.dumps(flow_data)

    #     # Replace embedding ID references
    #     if not DISABLE_INGEST_WITH_LANGFLOW and is_embedding:
    #         flow_json_str = re.sub(
    #             re.escape(old_embedding_id), new_embedding_id, flow_json_str
    #         )
    #         flow_json_str = re.sub(
    #             re.escape(old_embedding_id.split("-")[0]),
    #             new_embedding_id.split("-")[0],
    #             flow_json_str,
    #         )

    #     # Replace LLM ID references (if applicable)
    #     if old_llm_id and not is_embedding:
    #         flow_json_str = re.sub(
    #             re.escape(old_llm_id), new_llm_id, flow_json_str
    #         )

    #         flow_json_str = re.sub(
    #             re.escape(old_llm_id.split("-")[0]),
    #             new_llm_id.split("-")[0],
    #             flow_json_str,
    #         )
        
    #     # Replace text LLM ID references (if applicable)
    #     if old_llm_text_id and not is_embedding:
    #         flow_json_str = re.sub(
    #             re.escape(old_llm_text_id), new_llm_text_id, flow_json_str
    #         )

    #         flow_json_str = re.sub(
    #             re.escape(old_llm_text_id.split("-")[0]),
    #             new_llm_text_id.split("-")[0],
    #             flow_json_str,
    #         )

    #     # Convert back to JSON
    #     flow_data = json.loads(flow_json_str)

    #     # PATCH the updated flow
    #     response = await clients.langflow_request(
    #         "PATCH", f"/api/v1/flows/{flow_id}", json=flow_data
    #     )

    #     if response.status_code != 200:
    #         raise Exception(
    #             f"Failed to update flow: HTTP {response.status_code} - {response.text}"
    #         )

    #     return {
    #         "flow": flow_name,
    #         "success": True,
    #         "components_updated": components_updated,
    #         "flow_id": flow_id,
    #     }

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
        endpoint: str = None,
        flow_configs: list = None,
    ):
        """
        Change dropdown values for provider-specific components across flows

        Args:
            provider: The provider ("watsonx", "ollama", "openai", "anthropic")
            embedding_model: The embedding model name to set
            llm_model: The LLM model name to set
            endpoint: The endpoint URL (required for watsonx/ibm provider)
            flow_configs: Optional list of specific flow configs to update. If None, updates all flows.

        Returns:
            dict: Success/error response with details for each flow
        """
        if provider not in ["watsonx", "ollama", "openai", "anthropic"]:
            raise ValueError("provider must be 'watsonx', 'ollama', 'openai', or 'anthropic'")

        if provider == "watsonx" and not endpoint:
            raise ValueError("endpoint is required for watsonx provider")

        try:
            logger.info(
                f"Changing dropdown values for provider {provider}, embedding: {embedding_model}, llm: {llm_model}, endpoint: {endpoint}"
            )

            # Use provided flow_configs or default to all flows
            if flow_configs is None:
                flow_configs = [
                    {
                        "name": "nudges",
                        "flow_id": NUDGES_FLOW_ID,
                    },
                    {
                        "name": "retrieval",
                        "flow_id": LANGFLOW_CHAT_FLOW_ID,
                    },
                    {
                        "name": "ingest",
                        "flow_id": LANGFLOW_INGEST_FLOW_ID,
                    },
                    {
                        "name": "url_ingest",
                        "flow_id": LANGFLOW_URL_INGEST_FLOW_ID,
                    },
                ]

            # Determine target component IDs based on provider

            results = []

            # Process each flow sequentially
            for config in flow_configs:
                try:
                    result = await self._update_provider_components(
                        config,
                        provider,
                        embedding_model,
                        llm_model,
                        endpoint,
                    )
                    results.append(result)
                    logger.info(
                        f"Successfully updated {config['name']} flow with {provider} models"
                    )
                except Exception as e:
                    error_msg = f"Failed to update {config['name']} flow with {provider} models: {str(e)}"
                    logger.error(error_msg)
                    results.append(
                        {"flow": config["name"], "success": False, "error": error_msg}
                    )
                    # Continue with other flows even if one fails

            # Check if all flows were successful
            all_success = all(r.get("success", False) for r in results)

            return {
                "success": all_success,
                "message": f"Provider model update {'completed' if all_success else 'completed with errors'}",
                "provider": provider,
                "embedding_model": embedding_model,
                "llm_model": llm_model,
                "endpoint": endpoint,
                "results": results,
            }

        except Exception as e:
            logger.error(
                f"Error changing provider models for {provider}",
                error=str(e),
            )
            return {
                "success": False,
                "error": f"Failed to change provider models: {str(e)}",
            }

    # def _get_provider_component_ids(self, provider: str):
    #     """Get the component IDs for a specific provider"""
    #     if provider == "watsonx":
    #         return WATSONX_EMBEDDING_COMPONENT_DISPLAY_NAME, WATSONX_LLM_COMPONENT_DISPLAY_NAME
    #     elif provider == "ollama":
    #         return OLLAMA_EMBEDDING_COMPONENT_DISPLAY_NAME, OLLAMA_LLM_COMPONENT_DISPLAY_NAME
    #     elif provider == "openai":
    #         # OpenAI components are the default ones
    #         return OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME, OPENAI_LLM_COMPONENT_DISPLAY_NAME
    #     else:
    #         raise ValueError(f"Unsupported provider: {provider}")

    async def _update_provider_components(
        self,
        config,
        provider: str,
        embedding_model: str = None,
        llm_model: str = None,
        endpoint: str = None,
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
        if not DISABLE_INGEST_WITH_LANGFLOW and embedding_model:
            embedding_node, _ = self._find_node_in_flow(flow_data, display_name=OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME)
            if embedding_node:
                if await self._update_component_fields(
                    embedding_node, provider, embedding_model, endpoint
                ):
                    updates_made.append(f"embedding model: {embedding_model}")

        # Update LLM component (if exists in this flow)
        if llm_model:
            llm_node, _ = self._find_node_in_flow(flow_data, display_name=OPENAI_LLM_COMPONENT_DISPLAY_NAME)
            if llm_node:
                if await self._update_component_fields(
                    llm_node, provider, llm_model, endpoint
                ):
                    updates_made.append(f"llm model: {llm_model}")
            # Update LLM component (if exists in this flow)
            agent_node, _ = self._find_node_in_flow(flow_data, display_name=AGENT_COMPONENT_DISPLAY_NAME)
            if agent_node:
                if await self._update_component_fields(
                    agent_node, provider, llm_model, endpoint
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

    async def _update_component_fields(
        self,
        component_node,
        provider: str,
        model_value: str,
        endpoint: str = None,
    ):
        """Update fields in a component node based on provider and component type"""
        template = component_node.get("data", {}).get("node", {}).get("template", {})

        if not template:
            return False

        updated = False

        provider_name = "IBM watsonx.ai" if provider == "watsonx" else "Ollama" if provider == "ollama" else "Anthropic" if provider == "anthropic" else "OpenAI"

        field_name = "provider" if "provider" in template else "agent_llm"
        
        # Update provider field and call custom_component/update endpoint
        if field_name in template:
            # First, update the provider value
            template[field_name]["value"] = provider_name
            
            # Call custom_component/update endpoint to get updated template
            # Only call if code field exists (custom components should have code)
            if "code" in template and "value" in template["code"]:
                code_value = template["code"]["value"]
                field_value = provider_name
                                
                try:
                    update_payload = {
                        "code": code_value,
                        "template": template,
                        "field": field_name,
                        "field_value": field_value,
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
                            component_node["data"]["node"]["template"] = response_data["template"]
                            # Update local template reference
                            template = response_data["template"]
                            logger.info(f"Successfully updated template via custom_component/update for provider: {provider_name}")
                        else:
                            logger.warning("Response from custom_component/update missing 'data' field")
                    else:
                        logger.warning(
                            f"Failed to call custom_component/update: HTTP {response.status_code} - {response.text}"
                        )
                except Exception as e:
                    logger.error(f"Error calling custom_component/update: {str(e)}")
                    # Continue with manual updates even if API call fails
            
            updated = True
        

        # Update model_name field (common to all providers)
        if "model" in template:
            template["model"]["value"] = model_value
            template["model"]["options"] = [model_value]
            template["model"]["advanced"] = False
            updated = True
        elif "model_name" in template:
            template["model_name"]["value"] = model_value
            template["model_name"]["options"] = [model_value]
            template["model_name"]["advanced"] = False
            updated = True

        # Update endpoint/URL field based on provider
        if endpoint:
            if provider == "watsonx" and "base_url" in template:
                # Watson uses "url" field
                template["base_url"]["value"] = endpoint
                template["base_url"]["options"] = [endpoint]
                template["base_url"]["show"] = True
                template["base_url"]["advanced"] = False
                updated = True
            if provider == "watsonx" and "base_url_ibm_watsonx" in template:
                # Watson uses "url" field
                template["base_url_ibm_watsonx"]["value"] = endpoint
                template["base_url_ibm_watsonx"]["show"] = True
                template["base_url_ibm_watsonx"]["advanced"] = False
                updated = True

        if provider == "openai" and "api_key" in template:
            template["api_key"]["value"] = "OPENAI_API_KEY"
            template["api_key"]["load_from_db"] = True
            template["api_key"]["show"] = True
            template["api_key"]["advanced"] = False
            updated = True
        if provider == "openai" and "api_base" in template:
            template["api_base"]["value"] = ""
            template["api_base"]["load_from_db"] = False
            template["api_base"]["show"] = True
            template["api_base"]["advanced"] = False
            updated = True

        if provider == "anthropic" and "api_key" in template:
            template["api_key"]["value"] = "ANTHROPIC_API_KEY"
            template["api_key"]["load_from_db"] = True
            template["api_key"]["show"] = True
            template["api_key"]["advanced"] = False
            updated = True
        
        if provider == "anthropic" and "base_url" in template:
            template["base_url"]["value"] = "https://api.anthropic.com"
            template["base_url"]["load_from_db"] = False
            template["base_url"]["show"] = True
            template["base_url"]["advanced"] = True
            updated = True

        if provider == "ollama" and "base_url" in template:
            template["base_url"]["value"] = "OLLAMA_BASE_URL"
            template["base_url"]["load_from_db"] = True
            template["base_url"]["show"] = True
            template["base_url"]["advanced"] = False
            updated = True
        
        if provider == "ollama" and "api_base" in template:
            template["api_base"]["value"] = "OLLAMA_BASE_URL"
            template["api_base"]["load_from_db"] = True
            template["api_base"]["show"] = True
            template["api_base"]["advanced"] = False
            updated = True

        if provider == "ollama" and "ollama_base_url" in template:
            template["ollama_base_url"]["value"] = "OLLAMA_BASE_URL"
            template["ollama_base_url"]["load_from_db"] = True
            template["ollama_base_url"]["show"] = True
            template["ollama_base_url"]["advanced"] = False
            updated = True

        if provider == "watsonx" and "project_id" in template:
            template["project_id"]["value"] = "WATSONX_PROJECT_ID"
            template["project_id"]["load_from_db"] = True
            template["project_id"]["show"] = True
            template["project_id"]["advanced"] = False
            updated = True
        
        if provider == "watsonx" and "api_key" in template:
            template["api_key"]["value"] = "WATSONX_API_KEY"
            template["api_key"]["load_from_db"] = True
            template["api_key"]["show"] = True
            template["api_key"]["advanced"] = False
            updated = True

        return updated
