import uuid
import json
from typing import Any, Dict, Optional, List
from datetime import datetime
from config.settings import clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


class MonitorService:
    def __init__(self, session_manager=None, webhook_base_url: str = None):
        self.session_manager = session_manager
        self.webhook_base_url = webhook_base_url or "http://openrag-backend:8000"

    async def create_knowledge_filter_monitor(
        self,
        filter_id: str,
        filter_name: str,
        query_data: Dict[str, Any],
        user_id: str,
        jwt_token: str,
        notification_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Create a document-level monitor for a knowledge filter"""
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            subscription_id = str(uuid.uuid4())
            webhook_url = f"{self.webhook_base_url}/knowledge-filter/{filter_id}/webhook/{subscription_id}"

            # Convert knowledge filter query to monitor query format
            monitor_query = self._convert_kf_query_to_monitor_query(query_data)

            # TODO: OpenSearch 3.0 has a bug with document-level monitors on indexes with KNN fields
            # Error: "Cannot invoke KNNMethodConfigContext.getVectorDataType() because knnMethodConfigContext is null"
            # Consider using query-level monitors instead or excluding KNN fields from doc-level monitors
            # For now, this will fail on the 'documents' index due to chunk_embedding KNN field

            # Create the document-level monitor
            monitor_body = {
                "type": "monitor",
                "monitor_type": "doc_level_monitor",
                "name": f"KF Monitor: {filter_name}",
                "enabled": True,
                "schedule": {"period": {"interval": 1, "unit": "MINUTES"}},
                "inputs": [
                    {
                        "doc_level_input": {
                            "description": f"Monitor for knowledge filter: {filter_name}",
                            "indices": ["documents"],
                            "queries": [
                                {
                                    "id": f"kf_query_{filter_id}",
                                    "name": f"Knowledge Filter Query: {filter_name}",
                                    "query": monitor_query,
                                    "tags": [
                                        f"knowledge_filter:{filter_id}",
                                        f"user:{user_id}",
                                    ],
                                }
                            ],
                        }
                    }
                ],
                "triggers": [
                    {
                        "document_level_trigger": {
                            "name": f"KF Trigger: {filter_name}",
                            "severity": "1",
                            "condition": {
                                "script": {"source": "return true", "lang": "painless"}
                            },
                            "actions": [
                                {
                                    "name": f"KF Webhook Action: {filter_name}",
                                    "destination_id": await self._get_or_create_webhook_destination(
                                        webhook_url, opensearch_client
                                    ),
                                    "subject_template": {
                                        "source": f"Knowledge Filter Alert: {filter_name}",
                                        "lang": "mustache",
                                    },
                                    "message_template": {
                                        "source": json.dumps(
                                            {
                                                "filter_id": filter_id,
                                                "filter_name": filter_name,
                                                "subscription_id": subscription_id,
                                                "user_id": user_id,
                                                "timestamp": "{{ctx.trigger.timestamp}}",
                                                "findings": "{{ctx.results.0.hits.hits}}",
                                            }
                                        ),
                                        "lang": "mustache",
                                    },
                                }
                            ],
                        }
                    }
                ],
            }

            # Create the monitor
            response = await opensearch_client.transport.perform_request(
                "POST", "/_plugins/_alerting/monitors", body=monitor_body
            )

            if response.get("_id"):
                return {
                    "success": True,
                    "monitor_id": response["_id"],
                    "subscription_id": subscription_id,
                    "webhook_url": webhook_url,
                    "message": f"Monitor created successfully for knowledge filter: {filter_name}",
                }
            else:
                return {"success": False, "error": "Failed to create monitor"}

        except Exception as e:
            return {"success": False, "error": f"Monitor creation failed: {str(e)}"}

    async def delete_monitor(
        self, monitor_id: str, user_id: str, jwt_token: str
    ) -> Dict[str, Any]:
        """Delete a document-level monitor"""
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            response = await opensearch_client.transport.perform_request(
                "DELETE", f"/_plugins/_alerting/monitors/{monitor_id}"
            )

            if response.get("result") == "deleted":
                return {"success": True, "message": "Monitor deleted successfully"}
            else:
                return {"success": False, "error": "Failed to delete monitor"}

        except Exception as e:
            return {"success": False, "error": f"Monitor deletion failed: {str(e)}"}

    async def get_monitor(
        self, monitor_id: str, user_id: str, jwt_token: str
    ) -> Dict[str, Any]:
        """Get monitor details"""
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            response = await opensearch_client.transport.perform_request(
                "GET", f"/_plugins/_alerting/monitors/{monitor_id}"
            )

            if response.get("_id"):
                return {"success": True, "monitor": response}
            else:
                return {"success": False, "error": "Monitor not found"}

        except Exception as e:
            return {"success": False, "error": f"Failed to get monitor: {str(e)}"}

    async def list_user_monitors(
        self, user_id: str, jwt_token: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List all monitors for a specific user"""
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            # Search for all monitors (DLS will filter to user's monitors automatically)
            search_body = {
                "query": {
                    "bool": {"must": [{"term": {"monitor.type": "doc_level_monitor"}}]}
                },
                "sort": [{"monitor.last_update_time": {"order": "desc"}}],
                "size": limit,
            }

            response = await opensearch_client.search(
                index=".opendistro-alerting-config", body=search_body
            )

            monitors = []
            for hit in response.get("hits", {}).get("hits", []):
                monitor_data = hit["_source"]
                monitor_data["monitor_id"] = hit["_id"]
                monitors.append(monitor_data)

            return monitors

        except Exception as e:
            logger.error(
                "Error listing monitors for user", user_id=user_id, error=str(e)
            )
            return []

    async def list_monitors_for_filter(
        self, filter_id: str, user_id: str, jwt_token: str
    ) -> List[Dict[str, Any]]:
        """List all monitors for a specific knowledge filter"""
        try:
            opensearch_client = self.session_manager.get_user_opensearch_client(
                user_id, jwt_token
            )

            # Search for monitors with the knowledge filter tag
            search_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"monitor.type": "doc_level_monitor"}},
                            {
                                "term": {
                                    "monitor.inputs.doc_level_input.queries.tags": f"knowledge_filter:{filter_id}"
                                }
                            },
                        ]
                    }
                }
            }

            response = await opensearch_client.search(
                index=".opendistro-alerting-config", body=search_body
            )

            monitors = []
            for hit in response.get("hits", {}).get("hits", []):
                monitor_data = hit["_source"]
                monitor_data["monitor_id"] = hit["_id"]
                monitors.append(monitor_data)

            return monitors

        except Exception as e:
            logger.error(
                "Error listing monitors for filter", filter_id=filter_id, error=str(e)
            )
            return []

    async def _get_or_create_webhook_destination(
        self, webhook_url: str, opensearch_client
    ) -> str:
        """Get or create a webhook destination for notifications"""
        try:
            # Try to find existing webhook destination
            search_response = await opensearch_client.transport.perform_request(
                "GET",
                "/_plugins/_notifications/configs",
                params={"config_type": "webhook"},
            )

            # Check if we already have a destination for this webhook URL
            for config in search_response.get("config_list", []):
                if (
                    config.get("config", {}).get("webhook", {}).get("url")
                    == webhook_url
                ):
                    return config["config_id"]

            # Create new webhook destination
            destination_body = {
                "config": {
                    "name": f"KF Webhook {str(uuid.uuid4())[:8]}",
                    "description": "Knowledge Filter webhook notification",
                    "config_type": "webhook",
                    "is_enabled": True,
                    "webhook": {
                        "url": webhook_url,
                        "method": "POST",
                        "header_params": {"Content-Type": "application/json"},
                    },
                }
            }

            response = await opensearch_client.transport.perform_request(
                "POST", "/_plugins/_notifications/configs", body=destination_body
            )

            return response.get("config_id")

        except Exception as e:
            raise Exception(f"Failed to create webhook destination: {str(e)}")

    def _convert_kf_query_to_monitor_query(
        self, query_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert knowledge filter query format to OpenSearch monitor query format"""
        # This assumes the query_data contains an OpenSearch query structure
        # You may need to adjust this based on your actual knowledge filter query format

        if isinstance(query_data, dict) and "query" in query_data:
            # If it's already in OpenSearch query format, use it directly
            return query_data["query"]
        elif isinstance(query_data, dict):
            # If it's a direct query object, use it as-is
            return query_data
        else:
            # Fallback to match_all if format is unexpected
            return {"match_all": {}}
