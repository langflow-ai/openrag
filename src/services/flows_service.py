from config.settings import (
    NUDGES_FLOW_ID,
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    OLLAMA_LLM_TEXT_COMPONENT_ID,
    OLLAMA_LLM_TEXT_COMPONENT_PATH,
    OPENAI_EMBEDDING_COMPONENT_ID,
    OPENAI_LLM_COMPONENT_ID,
    OPENAI_LLM_TEXT_COMPONENT_ID,
    WATSONX_LLM_TEXT_COMPONENT_ID,
    WATSONX_LLM_TEXT_COMPONENT_PATH,
    clients,
    WATSONX_LLM_COMPONENT_PATH,
    WATSONX_EMBEDDING_COMPONENT_PATH,
    OLLAMA_LLM_COMPONENT_PATH,
    OLLAMA_EMBEDDING_COMPONENT_PATH,
    WATSONX_EMBEDDING_COMPONENT_ID,
    WATSONX_LLM_COMPONENT_ID,
    OLLAMA_EMBEDDING_COMPONENT_ID,
    OLLAMA_LLM_COMPONENT_ID,
)
import json
import os
import re
from utils.logging_config import get_logger

logger = get_logger(__name__)


class FlowsService:
    async def reset_langflow_flow(self, flow_type: str):
        """Reset a Langflow flow by uploading the corresponding JSON file

        Args:
            flow_type: Either 'nudges', 'retrieval', or 'ingest'

        Returns:
            dict: Success/error response
        """
        if not LANGFLOW_URL:
            raise ValueError("LANGFLOW_URL environment variable is required")

        # Determine flow file and ID based on type
        if flow_type == "nudges":
            flow_file = "flows/openrag_nudges.json"
            flow_id = NUDGES_FLOW_ID
        elif flow_type == "retrieval":
            flow_file = "flows/openrag_agent.json"
            flow_id = LANGFLOW_CHAT_FLOW_ID
        elif flow_type == "ingest":
            flow_file = "flows/ingestion_flow.json"
            flow_id = LANGFLOW_INGEST_FLOW_ID
        else:
            raise ValueError(
                "flow_type must be either 'nudges', 'retrieval', or 'ingest'"
            )

        # Load flow JSON file
        try:
            # Get the project root directory (go up from src/services/ to project root)
            # __file__ is src/services/chat_service.py
            # os.path.dirname(__file__) is src/services/
            # os.path.dirname(os.path.dirname(__file__)) is src/
            # os.path.dirname(os.path.dirname(os.path.dirname(__file__))) is project root
            current_file_dir = os.path.dirname(
                os.path.abspath(__file__)
            )  # src/services/
            src_dir = os.path.dirname(current_file_dir)  # src/
            project_root = os.path.dirname(src_dir)  # project root
            flow_path = os.path.join(project_root, flow_file)

            if not os.path.exists(flow_path):
                # List contents of project root to help debug
                try:
                    contents = os.listdir(project_root)
                    logger.info(f"Project root contents: {contents}")

                    flows_dir = os.path.join(project_root, "flows")
                    if os.path.exists(flows_dir):
                        flows_contents = os.listdir(flows_dir)
                        logger.info(f"Flows directory contents: {flows_contents}")
                    else:
                        logger.info("Flows directory does not exist")
                except Exception as e:
                    logger.error(f"Error listing directory contents: {e}")

                raise FileNotFoundError(f"Flow file not found at: {flow_path}")

            with open(flow_path, "r") as f:
                flow_data = json.load(f)
            logger.info(f"Successfully loaded flow data from {flow_file}")
        except FileNotFoundError:
            raise ValueError(f"Flow file not found: {flow_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in flow file {flow_file}: {e}")

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
                    flow_file=flow_file,
                )
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
            llm_template, embedding_template, llm_text_template = self._load_component_templates(provider)

            logger.info(f"Assigning {provider} components")

            # Define flow configurations
            flow_configs = [
                {
                    "name": "nudges",
                    "file": "flows/openrag_nudges.json",
                    "flow_id": NUDGES_FLOW_ID,
                    "embedding_id": OPENAI_EMBEDDING_COMPONENT_ID,
                    "llm_id": OPENAI_LLM_COMPONENT_ID,
                    "llm_text_id": OPENAI_LLM_TEXT_COMPONENT_ID,
                },
                {
                    "name": "retrieval",
                    "file": "flows/openrag_agent.json",
                    "flow_id": LANGFLOW_CHAT_FLOW_ID,
                    "embedding_id": OPENAI_EMBEDDING_COMPONENT_ID,
                    "llm_id": OPENAI_LLM_COMPONENT_ID,
                    "llm_text_id": None,
                },
                {
                    "name": "ingest",
                    "file": "flows/ingestion_flow.json",
                    "flow_id": LANGFLOW_INGEST_FLOW_ID,
                    "embedding_id": OPENAI_EMBEDDING_COMPONENT_ID,
                    "llm_id": None,  # Ingestion flow might not have LLM
                    "llm_text_id": None,  # Ingestion flow might not have LLM Text
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

    async def _update_flow_components(self, config, llm_template, embedding_template, llm_text_template):
        """Update components in a specific flow"""
        flow_name = config["name"]
        flow_file = config["file"]
        flow_id = config["flow_id"]
        old_embedding_id = config["embedding_id"]
        old_llm_id = config["llm_id"]
        old_llm_text_id = config["llm_text_id"]
        # Extract IDs from templates
        new_llm_id = llm_template["data"]["id"]
        new_embedding_id = embedding_template["data"]["id"]
        new_llm_text_id = llm_text_template["data"]["id"]
        # Get the project root directory
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.dirname(current_file_dir)
        project_root = os.path.dirname(src_dir)
        flow_path = os.path.join(project_root, flow_file)

        if not os.path.exists(flow_path):
            raise FileNotFoundError(f"Flow file not found at: {flow_path}")

        # Load flow JSON
        with open(flow_path, "r") as f:
            flow_data = json.load(f)

        # Find and replace components
        components_updated = []

        # Replace embedding component
        embedding_node = self._find_node_by_id(flow_data, old_embedding_id)
        if embedding_node:
            # Preserve position
            original_position = embedding_node.get("position", {})

            # Replace with new template
            new_embedding_node = embedding_template.copy()
            new_embedding_node["position"] = original_position

            # Replace in flow
            self._replace_node_in_flow(flow_data, old_embedding_id, new_embedding_node)
            components_updated.append(
                f"embedding: {old_embedding_id} -> {new_embedding_id}"
            )

        # Replace LLM component (if exists in this flow)
        if old_llm_id:
            llm_node = self._find_node_by_id(flow_data, old_llm_id)
            if llm_node:
                # Preserve position
                original_position = llm_node.get("position", {})

                # Replace with new template
                new_llm_node = llm_template.copy()
                new_llm_node["position"] = original_position

                # Replace in flow
                self._replace_node_in_flow(flow_data, old_llm_id, new_llm_node)
                components_updated.append(f"llm: {old_llm_id} -> {new_llm_id}")

        # Replace LLM component (if exists in this flow)
        if old_llm_text_id:
            llm_text_node = self._find_node_by_id(flow_data, old_llm_text_id)
            if llm_text_node:
                # Preserve position
                original_position = llm_text_node.get("position", {})

                # Replace with new template
                new_llm_text_node = llm_text_template.copy()
                new_llm_text_node["position"] = original_position

                # Replace in flow
                self._replace_node_in_flow(flow_data, old_llm_text_id, new_llm_text_node)
                components_updated.append(f"llm: {old_llm_text_id} -> {new_llm_text_id}")

        # Update all edge references using regex replacement
        flow_json_str = json.dumps(flow_data)

        # Replace embedding ID references
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

    def _find_node_by_id(self, flow_data, node_id):
        """Find a node by ID in the flow data"""
        nodes = flow_data.get("data", {}).get("nodes", [])
        for node in nodes:
            if node.get("id") == node_id:
                return node
        return None

    def _replace_node_in_flow(self, flow_data, old_id, new_node):
        """Replace a node in the flow data"""
        nodes = flow_data.get("data", {}).get("nodes", [])
        for i, node in enumerate(nodes):
            if node.get("id") == old_id:
                nodes[i] = new_node
                return True
        return False

    async def change_langflow_model_value(
        self, provider: str, embedding_model: str, llm_model: str, endpoint: str = None
    ):
        """
        Change dropdown values for provider-specific components across all flows

        Args:
            provider: The provider ("watsonx", "ollama", "openai")
            embedding_model: The embedding model name to set
            llm_model: The LLM model name to set
            endpoint: The endpoint URL (required for watsonx/ibm provider)

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

            # Define flow configurations with provider-specific component IDs
            flow_configs = [
                {
                    "name": "nudges",
                    "file": "flows/openrag_nudges.json",
                    "flow_id": NUDGES_FLOW_ID,
                },
                {
                    "name": "retrieval",
                    "file": "flows/openrag_agent.json",
                    "flow_id": LANGFLOW_CHAT_FLOW_ID,
                },
                {
                    "name": "ingest",
                    "file": "flows/ingestion_flow.json",
                    "flow_id": LANGFLOW_INGEST_FLOW_ID,
                },
            ]

            # Determine target component IDs based on provider
            target_embedding_id, target_llm_id, target_llm_text_id = self._get_provider_component_ids(
                provider
            )

            results = []

            # Process each flow sequentially
            for config in flow_configs:
                try:
                    result = await self._update_provider_components(
                        config,
                        provider,
                        target_embedding_id,
                        target_llm_id,
                        target_llm_text_id,
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
            return WATSONX_EMBEDDING_COMPONENT_ID, WATSONX_LLM_COMPONENT_ID, WATSONX_LLM_TEXT_COMPONENT_ID
        elif provider == "ollama":
            return OLLAMA_EMBEDDING_COMPONENT_ID, OLLAMA_LLM_COMPONENT_ID, OLLAMA_LLM_TEXT_COMPONENT_ID
        elif provider == "openai":
            # OpenAI components are the default ones
            return OPENAI_EMBEDDING_COMPONENT_ID, OPENAI_LLM_COMPONENT_ID, OPENAI_LLM_TEXT_COMPONENT_ID
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def _update_provider_components(
        self,
        config,
        provider: str,
        target_embedding_id: str,
        target_llm_id: str,
        target_llm_text_id: str,
        embedding_model: str,
        llm_model: str,
        endpoint: str = None,
    ):
        """Update provider components and their dropdown values in a flow"""
        flow_name = config["name"]
        flow_id = config["flow_id"]

        # Get flow data from Langflow API instead of file
        response = await clients.langflow_request(
            "GET", f"/api/v1/flows/{flow_id}"
        )
        
        if response.status_code != 200:
            raise Exception(
                f"Failed to get flow from Langflow: HTTP {response.status_code} - {response.text}"
            )
        
        flow_data = response.json()

        updates_made = []

        # Update embedding component
        embedding_node = self._find_node_by_id(flow_data, target_embedding_id)
        if embedding_node:
            if self._update_component_fields(
                embedding_node, provider, embedding_model, endpoint
            ):
                updates_made.append(f"embedding model: {embedding_model}")

        # Update LLM component (if exists in this flow)
        if target_llm_id:
            llm_node = self._find_node_by_id(flow_data, target_llm_id)
            if llm_node:
                if self._update_component_fields(
                    llm_node, provider, llm_model, endpoint
                ):
                    updates_made.append(f"llm model: {llm_model}")

        if target_llm_text_id:
            llm_text_node = self._find_node_by_id(flow_data, target_llm_text_id)
            if llm_text_node:
                if self._update_component_fields(
                    llm_text_node, provider, llm_model, endpoint
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
            elif provider == "ollama" and "base_url" in template:
                # Ollama uses "base_url" field
                template["base_url"]["value"] = endpoint
                # Note: base_url is typically a MessageTextInput, not dropdown, so no options field
                updated = True

        return updated
