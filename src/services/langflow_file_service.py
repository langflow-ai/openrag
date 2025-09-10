from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from services.flow_validation_context import FlowComponentInfo

from config.settings import LANGFLOW_INGEST_FLOW_ID, clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LangflowFileService:
    def __init__(self):
        self.flow_id_ingest = LANGFLOW_INGEST_FLOW_ID

    async def upload_user_file(
        self, file_tuple, jwt_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload a file using Langflow Files API v2: POST /api/v2/files.
        Returns JSON with keys: id, name, path, size, provider.
        """
        logger.debug("[LF] Upload (v2) -> /api/v2/files")
        resp = await clients.langflow_request(
            "POST",
            "/api/v2/files",
            files={"file": file_tuple},
            headers={"Content-Type": None},
        )
        logger.debug(
            "[LF] Upload response",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Upload failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text,
            )
        resp.raise_for_status()
        return resp.json()

    async def delete_user_file(self, file_id: str) -> None:
        """Delete a file by id using v2: DELETE /api/v2/files/{id}."""
        # NOTE: use v2 root, not /api/v1
        logger.debug("[LF] Delete (v2) -> /api/v2/files/{id}", file_id=file_id)
        resp = await clients.langflow_request("DELETE", f"/api/v2/files/{file_id}")
        logger.debug(
            "[LF] Delete response",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Delete failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text[:500],
            )
        resp.raise_for_status()

    async def _fetch_flow_definition(self, flow_id: str) -> Dict[str, Any]:
        """Fetch flow definition from Langflow API."""
        response = await clients.langflow_request("GET", f"/api/v1/flows/{flow_id}")

        if response.status_code == 404:
            raise ValueError(f"Flow '{flow_id}' not found")
        elif response.status_code != 200:
            raise ValueError(
                f"Failed to fetch flow definition: HTTP {response.status_code}"
            )

        return response.json()

    def _extract_components_from_flow(
        self, flow_data: Dict[str, Any]
    ) -> "FlowComponentInfo":
        """Extract components and their parameters from flow data."""
        from services.flow_validation_context import (
            ComponentInfo,
            ComponentParameter,
            FlowComponentInfo,
        )

        nodes = flow_data.get("data", {}).get("nodes", [])
        if not nodes:
            raise ValueError("Flow contains no components")

        components = {}
        target_components = [
            "File",
            "Split Text",
            "OpenAI Embeddings",
            "OpenSearch (Hybrid)",
        ]

        for node in nodes:
            data = node.get("data", {})
            node_data = data.get("node", {})
            display_name = node_data.get("display_name", "")
            node_id = node.get("id", "")

            if display_name in target_components:
                # Extract parameter information from the node template
                parameters = {}
                template = node_data.get("template", {})  # Template is in node_data

                for param_name, param_data in template.items():
                    if isinstance(param_data, dict):
                        param_info = ComponentParameter(
                            name=param_name,
                            display_name=param_data.get("display_name", param_name),
                            param_type=param_data.get("type", "unknown"),
                            value=param_data.get("value"),
                            options=param_data.get("options", []),
                            advanced=param_data.get("advanced", False),
                            required=param_data.get("required", False),
                        )
                        parameters[param_name] = param_info

                component_info = ComponentInfo(
                    display_name=display_name,
                    component_type=node_data.get("type", ""),
                    node_id=node_id,
                    parameters=parameters,
                )

                if display_name not in components:
                    components[display_name] = []
                components[display_name].append(component_info)

        return FlowComponentInfo(
            components=components,
            flow_id=self.flow_id_ingest,
        )

    def _validate_component_requirements(
        self, component_info: "FlowComponentInfo"
    ) -> None:
        """Validate that required components are present in correct quantities."""
        # File component validation
        file_count = len(component_info.components.get("File", []))
        if file_count == 0:
            raise ValueError(
                "Flow validation failed: No 'File' component found. "
                "The ingestion flow must contain exactly one File component."
            )
        elif file_count > 1:
            raise ValueError(
                f"Flow validation failed: Found {file_count} 'File' components. "
                f"The ingestion flow must contain exactly one File component."
            )

        # OpenSearch component validation
        opensearch_count = len(component_info.components.get("OpenSearch (Hybrid)", []))
        if opensearch_count == 0:
            raise ValueError(
                "Flow validation failed: No 'OpenSearch (Hybrid)' component found. "
                "The ingestion flow must contain at least one OpenSearch (Hybrid) component."
            )
        elif opensearch_count > 1:
            logger.warning(
                f"[LF] Flow contains {opensearch_count} OpenSearch (Hybrid) components. "
                f"Tweaks will be applied to all components with this display name."
            )

        # Optional component warnings
        if not component_info.has_split_text:
            logger.warning(
                "[LF] No 'Split Text' component found. Text chunking may not work as expected."
            )

        if not component_info.has_openai_embeddings:
            logger.warning(
                "[LF] No 'OpenAI Embeddings' component found. Embedding generation may not work as expected."
            )

    async def validate_ingestion_flow(
        self, use_cache: bool = True
    ) -> "FlowComponentInfo":
        """
        Validate the ingestion flow structure to ensure it has required components.

        Args:
            use_cache: Whether to use cached validation results (default: True)

        Returns:
            FlowComponentInfo: Component information if validation passes

        Raises:
            ValueError: If flow is not configured, not found, or doesn't meet requirements
        """
        if not self.flow_id_ingest:
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        # Check cache first
        if use_cache:
            from services.flow_validation_context import get_cached_flow_validation

            cached_info = await get_cached_flow_validation(self.flow_id_ingest)
            if cached_info:
                logger.debug(
                    f"[LF] Using cached validation for flow: {self.flow_id_ingest}"
                )
                return cached_info

        logger.debug(f"[LF] Validating ingestion flow: {self.flow_id_ingest}")

        try:
            # Fetch flow definition
            flow_data = await self._fetch_flow_definition(self.flow_id_ingest)

            # Extract and analyze components
            component_info = self._extract_components_from_flow(flow_data)

            # Validate requirements
            self._validate_component_requirements(component_info)

            # Cache the results
            from services.flow_validation_context import cache_flow_validation

            await cache_flow_validation(self.flow_id_ingest, component_info)

            # Log successful validation
            logger.info(
                f"[LF] Flow validation passed for '{self.flow_id_ingest}': "
                f"File={len(component_info.components.get('File', []))}, "
                f"OpenSearch={len(component_info.components.get('OpenSearch (Hybrid)', []))}, "
                f"SplitText={len(component_info.components.get('Split Text', []))}, "
                f"Embeddings={len(component_info.components.get('OpenAI Embeddings', []))}, "
                f"Other={len([c for comp_list in component_info.components.values() for c in comp_list if c.display_name not in ['File', 'Split Text', 'OpenAI Embeddings', 'OpenSearch (Hybrid)']])}, "
                f"Available settings: {list(component_info.available_ui_settings.keys())}"
            )

            return component_info

        except Exception as e:
            logger.error(
                f"[LF] Flow validation failed for '{self.flow_id_ingest}': {e}"
            )
            raise

    async def run_ingestion_flow(
        self,
        file_paths: List[str],
        jwt_token: str,
        session_id: Optional[str] = None,
        tweaks: Optional[Dict[str, Any]] = None,
        owner: Optional[str] = None,
        owner_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        connector_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Trigger the ingestion flow with provided file paths.
        The flow must expose a File component path in input schema or accept files parameter.
        """
        if not self.flow_id_ingest:
            logger.error("[LF] LANGFLOW_INGEST_FLOW_ID is not configured")
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        # Validate flow structure before proceeding
        try:
            await self.validate_ingestion_flow()
        except Exception as e:
            logger.error(f"[LF] Flow validation failed: {e}")
            raise ValueError(f"Ingestion flow validation failed: {e}")

        payload: Dict[str, Any] = {
            "input_value": "Ingest files",
            "input_type": "chat",
            "output_type": "text",  # Changed from "json" to "text"
        }
        if not tweaks:
            tweaks = {}

        # Pass files via tweaks to File component
        if file_paths:
            tweaks["File"] = {"path": file_paths}

        # Pass JWT token via tweaks to OpenSearch component
        if jwt_token:
            tweaks["OpenSearch (Hybrid)"] = {"jwt_token": jwt_token}
            logger.debug("[LF] Added JWT token to tweaks for OpenSearch components")
        else:
            logger.warning("[LF] No JWT token provided")

        # Pass metadata via tweaks to OpenSearch component
        metadata_tweaks = []
        if owner:
            metadata_tweaks.append({"key": "owner", "value": owner})
        if owner_name:
            metadata_tweaks.append({"key": "owner_name", "value": owner_name})
        if owner_email:
            metadata_tweaks.append({"key": "owner_email", "value": owner_email})
        if connector_type:
            metadata_tweaks.append({"key": "connector_type", "value": connector_type})

        if metadata_tweaks:
            # Initialize the OpenSearch component tweaks if not already present
            if "OpenSearch (Hybrid)" not in tweaks:
                tweaks["OpenSearch (Hybrid)"] = {}
            tweaks["OpenSearch (Hybrid)"]["docs_metadata"] = metadata_tweaks
            logger.debug(
                "[LF] Added metadata to tweaks", metadata_count=len(metadata_tweaks)
            )
        if tweaks:
            payload["tweaks"] = tweaks
        if session_id:
            payload["session_id"] = session_id

        logger.debug(
            "[LF] Run ingestion -> /run/%s | files=%s session_id=%s tweaks_keys=%s jwt_present=%s",
            self.flow_id_ingest,
            len(file_paths) if file_paths else 0,
            session_id,
            list(tweaks.keys()) if isinstance(tweaks, dict) else None,
            bool(jwt_token),
        )

        # Avoid logging full payload to prevent leaking sensitive data (e.g., JWT)

        resp = await clients.langflow_request(
            "POST", f"/api/v1/run/{self.flow_id_ingest}", json=payload
        )
        logger.debug(
            "[LF] Run response", status_code=resp.status_code, reason=resp.reason_phrase
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Run failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text[:1000],
            )
        resp.raise_for_status()
        try:
            resp_json = resp.json()
        except Exception as e:
            logger.error(
                "[LF] Failed to parse run response as JSON",
                body=resp.text[:1000],
                error=str(e),
            )
            raise
        return resp_json

    async def upload_and_ingest_file(
        self,
        file_tuple,
        session_id: Optional[str] = None,
        tweaks: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        jwt_token: Optional[str] = None,
        delete_after_ingest: bool = True,
    ) -> Dict[str, Any]:
        """
        Combined upload, ingest, and delete operation.
        First uploads the file, then runs ingestion on it, then optionally deletes the file.

        Args:
            file_tuple: File tuple (filename, content, content_type)
            session_id: Optional session ID for the ingestion flow
            tweaks: Optional tweaks for the ingestion flow
            settings: Optional UI settings to convert to component tweaks
            jwt_token: Optional JWT token for authentication
            delete_after_ingest: Whether to delete the file from Langflow after ingestion (default: True)

        Returns:
            Combined result with upload info, ingestion result, and deletion status
        """
        logger.debug("[LF] Starting combined upload and ingest operation")

        # Step 1: Upload the file
        try:
            upload_result = await self.upload_user_file(file_tuple, jwt_token=jwt_token)
            logger.debug(
                "[LF] Upload completed successfully",
                extra={
                    "file_id": upload_result.get("id"),
                    "file_path": upload_result.get("path"),
                },
            )
        except Exception as e:
            logger.error(
                "[LF] Upload failed during combined operation", extra={"error": str(e)}
            )
            raise Exception(f"Upload failed: {str(e)}")

        # Step 2: Prepare for ingestion
        file_path = upload_result.get("path")
        if not file_path:
            raise ValueError("Upload successful but no file path returned")

        # Convert UI settings to component tweaks if provided
        final_tweaks = tweaks.copy() if tweaks else {}

        if settings:
            logger.debug(
                "[LF] Applying ingestion settings", extra={"settings": settings}
            )

            # Split Text component tweaks
            if (
                settings.get("chunkSize")
                or settings.get("chunkOverlap")
                or settings.get("separator")
            ):
                if "Split Text" not in final_tweaks:
                    final_tweaks["Split Text"] = {}
                if settings.get("chunkSize"):
                    final_tweaks["Split Text"]["chunk_size"] = settings["chunkSize"]
                if settings.get("chunkOverlap"):
                    final_tweaks["Split Text"]["chunk_overlap"] = settings[
                        "chunkOverlap"
                    ]
                if settings.get("separator"):
                    final_tweaks["Split Text"]["separator"] = settings["separator"]

            # OpenAI Embeddings component tweaks
            if settings.get("embeddingModel"):
                if "OpenAI Embeddings" not in final_tweaks:
                    final_tweaks["OpenAI Embeddings"] = {}
                final_tweaks["OpenAI Embeddings"]["model"] = settings["embeddingModel"]

            logger.debug(
                "[LF] Final tweaks with settings applied",
                extra={"tweaks": final_tweaks},
            )

        # Step 3: Run ingestion
        try:
            ingest_result = await self.run_ingestion_flow(
                file_paths=[file_path],
                session_id=session_id,
                tweaks=final_tweaks,
                jwt_token=jwt_token,
            )
            logger.debug("[LF] Ingestion completed successfully")
        except Exception as e:
            logger.error(
                "[LF] Ingestion failed during combined operation",
                extra={"error": str(e), "file_path": file_path},
            )
            # Note: We could optionally delete the uploaded file here if ingestion fails
            raise Exception(f"Ingestion failed: {str(e)}")

        # Step 4: Delete file from Langflow (optional)
        file_id = upload_result.get("id")
        delete_result = None
        delete_error = None

        if delete_after_ingest and file_id:
            try:
                logger.debug(
                    "[LF] Deleting file after successful ingestion",
                    extra={"file_id": file_id},
                )
                await self.delete_user_file(file_id)
                delete_result = {"status": "deleted", "file_id": file_id}
                logger.debug("[LF] File deleted successfully")
            except Exception as e:
                delete_error = str(e)
                logger.warning(
                    "[LF] Failed to delete file after ingestion",
                    extra={"error": delete_error, "file_id": file_id},
                )
                delete_result = {
                    "status": "delete_failed",
                    "file_id": file_id,
                    "error": delete_error,
                }

        # Return combined result
        result = {
            "status": "success",
            "upload": upload_result,
            "ingestion": ingest_result,
            "message": f"File '{upload_result.get('name')}' uploaded and ingested successfully",
        }

        if delete_after_ingest:
            result["deletion"] = delete_result
            if delete_result and delete_result.get("status") == "deleted":
                result["message"] += " and cleaned up"
            elif delete_error:
                result["message"] += f" (cleanup warning: {delete_error})"

        return result
