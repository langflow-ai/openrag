from starlette.responses import JSONResponse
from config.settings import (
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    LANGFLOW_PUBLIC_URL,
    clients,
)


async def get_settings(request, session_manager):
    """Get application settings"""
    try:
        # Return public settings that are safe to expose to frontend
        settings = {
            "langflow_url": LANGFLOW_URL,
            "flow_id": LANGFLOW_CHAT_FLOW_ID,
            "ingest_flow_id": LANGFLOW_INGEST_FLOW_ID,
            "langflow_public_url": LANGFLOW_PUBLIC_URL,
        }

        # Only expose edit URLs when a public URL is configured
        if LANGFLOW_PUBLIC_URL and LANGFLOW_CHAT_FLOW_ID:
            settings["langflow_edit_url"] = (
                f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_CHAT_FLOW_ID}"
            )

        if LANGFLOW_PUBLIC_URL and LANGFLOW_INGEST_FLOW_ID:
            settings["langflow_ingest_edit_url"] = (
                f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_INGEST_FLOW_ID}"
            )

        # Fetch ingestion flow configuration to get actual component defaults
        if LANGFLOW_INGEST_FLOW_ID:
            try:
                response = await clients.langflow_request(
                    "GET",
                    f"/api/v1/flows/{LANGFLOW_INGEST_FLOW_ID}"
                )
                if response.status_code == 200:
                    flow_data = response.json()

                    # Extract component defaults (ingestion-specific settings only)
                    ingestion_defaults = {
                        "chunkSize": 1000,
                        "chunkOverlap": 200,
                        "separator": "\\n",
                        "embeddingModel": "text-embedding-3-small",
                    }

                    if flow_data.get("data", {}).get("nodes"):
                        for node in flow_data["data"]["nodes"]:
                            node_template = (
                                node.get("data", {})
                                .get("node", {})
                                .get("template", {})
                            )

                            # Split Text component (SplitText-QIKhg)
                            if node.get("id") == "SplitText-QIKhg":
                                if node_template.get("chunk_size", {}).get(
                                    "value"
                                ):
                                    ingestion_defaults["chunkSize"] = (
                                        node_template["chunk_size"]["value"]
                                    )
                                if node_template.get("chunk_overlap", {}).get(
                                    "value"
                                ):
                                    ingestion_defaults["chunkOverlap"] = (
                                        node_template["chunk_overlap"]["value"]
                                    )
                                if node_template.get("separator", {}).get(
                                    "value"
                                ):
                                    ingestion_defaults["separator"] = (
                                        node_template["separator"]["value"]
                                    )

                            # OpenAI Embeddings component (OpenAIEmbeddings-joRJ6)
                            elif node.get("id") == "OpenAIEmbeddings-joRJ6":
                                if node_template.get("model", {}).get("value"):
                                    ingestion_defaults["embeddingModel"] = (
                                        node_template["model"]["value"]
                                    )

                            # Note: OpenSearch component settings are not exposed for ingestion
                            # (search-related parameters like number_of_results, score_threshold
                            # are for retrieval, not ingestion)

                    settings["ingestion_defaults"] = ingestion_defaults

            except Exception as e:
                print(f"[WARNING] Failed to fetch ingestion flow defaults: {e}")
                # Continue without ingestion defaults

        return JSONResponse(settings)

    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to retrieve settings: {str(e)}"}, status_code=500
        )
