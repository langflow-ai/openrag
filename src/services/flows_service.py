from config.settings import (
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
from utils.logging_config import get_logger

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

                        provider = config.provider.model_provider.lower()

                        # Step 1: Assign model provider (replace components) if not OpenAI
                        if provider != "openai":
                            logger.info(
                                f"Assigning {provider} components to {flow_type} flow"
                            )
                            provider_result = await self.assign_model_provider(provider)

                            if not provider_result.get("success"):
                                logger.warning(
                                    f"Failed to assign {provider} components: {provider_result.get('error', 'Unknown error')}"
                                )
                                # Continue anyway, maybe just value updates will work

                        # Step 2: Update model values for the specific flow being reset
                        single_flow_config = [
                            {
                                "name": flow_type,
                                "flow_id": flow_id,
                            }
                        ]

                        logger.info(f"Updating {flow_type} flow model values")
                        update_result = await self.change_langflow_model_value(
                            provider=provider,
                            embedding_model=config.knowledge.embedding_model,
                            llm_model=config.agent.llm_model,
                            endpoint=config.provider.endpoint
                            if config.provider.endpoint
                            else None,
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

    async def assign_model_provider(self, provider: str):
        """
        Replace OpenAI components with the specified provider components in all flows

        Args:
            provider: "watsonx", "ollama", or "openai"

        Returns:
            dict: Success/error response with details for each flow
        """
        if provider not in ["watsonx", "ollama", "openai"]:
            raise ValueError("provider must be 'watsonx', 'ollama', or 'openai'")

        if provider == "openai":
            logger.info("Provider is already OpenAI, no changes needed")
            return {
                "success": True,
                "message": "Provider is already OpenAI, no changes needed",
            }

        try:
            # Load component templates based on provider
            llm_template, embedding_template, llm_text_template = (
                self._load_component_templates(provider)
            )

            logger.info(f"Assigning {provider} components")

            # Define flow configurations (removed hardcoded file paths)
            flow_configs = [
                {
                    "name": "nudges",
                    "flow_id": NUDGES_FLOW_ID,
                    "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
                    "llm_text_name": OPENAI_LLM_COMPONENT_DISPLAY_NAME,
                    "llm_name": None,
                },
                {
                    "name": "retrieval",
                    "flow_id": LANGFLOW_CHAT_FLOW_ID,
                    "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
                    "llm_name": OPENAI_LLM_COMPONENT_DISPLAY_NAME,
                    "llm_text_name": None,
                },
                {
                    "name": "ingest",
                    "flow_id": LANGFLOW_INGEST_FLOW_ID,
                    "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
                    "llm_name": None,  # Ingestion flow might not have LLM
                    "llm_text_name": None,
                },
                {
                    "name": "url_ingest",
                    "flow_id": LANGFLOW_URL_INGEST_FLOW_ID,
                    "embedding_name": OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME,
                    "llm_name": None,
                    "llm_text_name": None,
                },
            ]

            results = []

            # Process each flow sequentially
            for config in flow_configs:
                try:
                    result = await self._update_flow_components(
                        config, llm_template, embedding_template, llm_text_template
                    )
                    results.append(result)
                    logger.info(f"Successfully updated {config['name']} flow")
                except Exception as e:
                    error_msg = f"Failed to update {config['name']} flow: {str(e)}"
                    logger.error(error_msg)
                    results.append(
                        {"flow": config["name"], "success": False, "error": error_msg}
                    )
                    # Continue with other flows even if one fails

            # Check if all flows were successful
            all_success = all(r.get("success", False) for r in results)

            return {
                "success": all_success,
                "message": f"Model provider assignment to {provider} {'completed' if all_success else 'completed with errors'}",
                "provider": provider,
                "results": results,
            }

        except Exception as e:
            logger.error(f"Error assigning model provider {provider}", error=str(e))
            return {
                "success": False,
                "error": f"Failed to assign model provider: {str(e)}",
            }

    def _load_component_templates(self, provider: str):
        """Load component templates for the specified provider"""
        if provider == "watsonx":
            llm_path = WATSONX_LLM_COMPONENT_PATH
            embedding_path = WATSONX_EMBEDDING_COMPONENT_PATH
            llm_text_path = WATSONX_LLM_TEXT_COMPONENT_PATH
        elif provider == "ollama":
            llm_path = OLLAMA_LLM_COMPONENT_PATH
            embedding_path = OLLAMA_EMBEDDING_COMPONENT_PATH
            llm_text_path = OLLAMA_LLM_TEXT_COMPONENT_PATH
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Get the project root directory (same logic as reset_langflow_flow)
        current_file_dir = os.path.dirname(os.path.abspath(__file__))  # src/services/
        src_dir = os.path.dirname(current_file_dir)  # src/
        project_root = os.path.dirname(src_dir)  # project root

        # Load LLM template
        llm_full_path = os.path.join(project_root, llm_path)
        if not os.path.exists(llm_full_path):
            raise FileNotFoundError(
                f"LLM component template not found at: {llm_full_path}"
            )

        with open(llm_full_path, "r") as f:
            llm_template = json.load(f)

        # Load embedding template
        embedding_full_path = os.path.join(project_root, embedding_path)
        if not os.path.exists(embedding_full_path):
            raise FileNotFoundError(
                f"Embedding component template not found at: {embedding_full_path}"
            )

        with open(embedding_full_path, "r") as f:
            embedding_template = json.load(f)

        # Load LLM Text template
        llm_text_full_path = os.path.join(project_root, llm_text_path)
        if not os.path.exists(llm_text_full_path):
            raise FileNotFoundError(
                f"LLM Text component template not found at: {llm_text_full_path}"
            )

        with open(llm_text_full_path, "r") as f:
            llm_text_template = json.load(f)

        logger.info(f"Loaded component templates for {provider}")
        return llm_template, embedding_template, llm_text_template

    async def _update_flow_components(
        self, config, llm_template, embedding_template, llm_text_template
    ):
        """Update components in a specific flow"""
        flow_name = config["name"]
        flow_id = config["flow_id"]
        old_embedding_name = config["embedding_name"]
        old_llm_name = config["llm_name"]
        old_llm_text_name = config["llm_text_name"]
        # Extract IDs from templates
        new_llm_id = llm_template["data"]["id"]
        new_embedding_id = embedding_template["data"]["id"]
        new_llm_text_id = llm_text_template["data"]["id"]

        # Dynamically find the flow file by ID
        flow_path = self._find_flow_file_by_id(flow_id)
        if not flow_path:
            raise FileNotFoundError(f"Flow file not found for flow ID: {flow_id}")

        # Load flow JSON
        with open(flow_path, "r") as f:
            flow_data = json.load(f)

        # Find and replace components
        components_updated = []

        # Replace embedding component
        if not DISABLE_INGEST_WITH_LANGFLOW:
            embedding_node, _ = self._find_node_in_flow(flow_data, display_name=old_embedding_name)
            if embedding_node:
                # Preserve position
                original_position = embedding_node.get("position", {})

                # Replace with new template
                new_embedding_node = embedding_template.copy()
                new_embedding_node["position"] = original_position

                # Replace in flow
                self._replace_node_in_flow(flow_data, old_embedding_name, new_embedding_node)
                components_updated.append(
                    f"embedding: {old_embedding_name} -> {new_embedding_id}"
                )

        # Replace LLM component (if exists in this flow)
        if old_llm_name:
            llm_node, _ = self._find_node_in_flow(flow_data, display_name=old_llm_name)
            if llm_node:
                # Preserve position
                original_position = llm_node.get("position", {})

                # Replace with new template
                new_llm_node = llm_template.copy()
                new_llm_node["position"] = original_position

                # Replace in flow
                self._replace_node_in_flow(flow_data, old_llm_name, new_llm_node)
                components_updated.append(f"llm: {old_llm_name} -> {new_llm_id}")

        # Replace LLM component (if exists in this flow)
        if old_llm_text_name:
            llm_text_node, _ = self._find_node_in_flow(flow_data, display_name=old_llm_text_name)
            if llm_text_node:
                # Preserve position
                original_position = llm_text_node.get("position", {})

                # Replace with new template
                new_llm_text_node = llm_text_template.copy()
                new_llm_text_node["position"] = original_position

                # Replace in flow
                self._replace_node_in_flow(flow_data, old_llm_text_name, new_llm_text_node)
                components_updated.append(f"llm: {old_llm_text_name} -> {new_llm_text_id}")

        old_embedding_id = None
        old_llm_id = None
        old_llm_text_id = None
        if embedding_node:
            old_embedding_id = embedding_node.get("data", {}).get("id")
        if old_llm_name and llm_node:
            old_llm_id = llm_node.get("data", {}).get("id")
        if old_llm_text_name and llm_text_node:
            old_llm_text_id = llm_text_node.get("data", {}).get("id")

        # Update all edge references using regex replacement
        flow_json_str = json.dumps(flow_data)

        # Replace embedding ID references
        if not DISABLE_INGEST_WITH_LANGFLOW:
            flow_json_str = re.sub(
                re.escape(old_embedding_id), new_embedding_id, flow_json_str
            )
            flow_json_str = re.sub(
                re.escape(old_embedding_id.split("-")[0]),
                new_embedding_id.split("-")[0],
                flow_json_str,
            )

        # Replace LLM ID references (if applicable)
        if old_llm_id:
            flow_json_str = re.sub(
                re.escape(old_llm_id), new_llm_id, flow_json_str
            )

            flow_json_str = re.sub(
                re.escape(old_llm_id.split("-")[0]),
                new_llm_id.split("-")[0],
                flow_json_str,
            )
        
        # Replace text LLM ID references (if applicable)
        if old_llm_text_id:
            flow_json_str = re.sub(
                re.escape(old_llm_text_id), new_llm_text_id, flow_json_str
            )

            flow_json_str = re.sub(
                re.escape(old_llm_text_id.split("-")[0]),
                new_llm_text_id.split("-")[0],
                flow_json_str,
            )

        # Convert back to JSON
        flow_data = json.loads(flow_json_str)

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
            "components_updated": components_updated,
            "flow_id": flow_id,
        }

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

    async def change_langflow_model_value(
        self,
        provider: str,
        embedding_model: str,
        llm_model: str,
        endpoint: str = None,
        flow_configs: list = None,
    ):
        """
        Change dropdown values for provider-specific components across flows

        Args:
            provider: The provider ("watsonx", "ollama", "openai")
            embedding_model: The embedding model name to set
            llm_model: The LLM model name to set
            endpoint: The endpoint URL (required for watsonx/ibm provider)
            flow_configs: Optional list of specific flow configs to update. If None, updates all flows.

        Returns:
            dict: Success/error response with details for each flow
        """
        if provider not in ["watsonx", "ollama", "openai"]:
            raise ValueError("provider must be 'watsonx', 'ollama', or 'openai'")

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
            target_embedding_name, target_llm_name = self._get_provider_component_ids(
                provider
            )

            results = []

            # Process each flow sequentially
            for config in flow_configs:
                try:
                    result = await self._update_provider_components(
                        config,
                        provider,
                        target_embedding_name,
                        target_llm_name,
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

    def _get_provider_component_ids(self, provider: str):
        """Get the component IDs for a specific provider"""
        if provider == "watsonx":
            return WATSONX_EMBEDDING_COMPONENT_DISPLAY_NAME, WATSONX_LLM_COMPONENT_DISPLAY_NAME
        elif provider == "ollama":
            return OLLAMA_EMBEDDING_COMPONENT_DISPLAY_NAME, OLLAMA_LLM_COMPONENT_DISPLAY_NAME
        elif provider == "openai":
            # OpenAI components are the default ones
            return OPENAI_EMBEDDING_COMPONENT_DISPLAY_NAME, OPENAI_LLM_COMPONENT_DISPLAY_NAME
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def _update_provider_components(
        self,
        config,
        provider: str,
        target_embedding_name: str,
        target_llm_name: str,
        embedding_model: str,
        llm_model: str,
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
        if not DISABLE_INGEST_WITH_LANGFLOW:
            embedding_node, _ = self._find_node_in_flow(flow_data, display_name=target_embedding_name)
            if embedding_node:
                if self._update_component_fields(
                    embedding_node, provider, embedding_model, endpoint
                ):
                    updates_made.append(f"embedding model: {embedding_model}")

        # Update LLM component (if exists in this flow)
        if target_llm_name:
            llm_node, _ = self._find_node_in_flow(flow_data, display_name=target_llm_name)
            if llm_node:
                if self._update_component_fields(
                    llm_node, provider, llm_model, endpoint
                ):
                    updates_made.append(f"llm model: {llm_model}")

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

    def _update_component_fields(
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

        # Update model_name field (common to all providers)
        if provider == "openai" and "model" in template:
            template["model"]["value"] = model_value
            template["model"]["options"] = [model_value]
            updated = True
        elif "model_name" in template:
            template["model_name"]["value"] = model_value
            template["model_name"]["options"] = [model_value]
            updated = True

        # Update endpoint/URL field based on provider
        if endpoint:
            if provider == "watsonx" and "url" in template:
                # Watson uses "url" field
                template["url"]["value"] = endpoint
                template["url"]["options"] = [endpoint]
                updated = True

        return updated
