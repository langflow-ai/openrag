import json
from typing import Any

from agent import async_langflow
from auth_context import set_auth_context
from config.settings import (
    DISABLE_CHAT_WITH_LANGFLOW,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_URL,
    NUDGES_FLOW_ID,
    clients,
)
from utils.langflow_utils import fence_untrusted_text
from utils.logging_config import get_logger
from utils.opensearch_queries import build_filter_clauses

logger = get_logger(__name__)


class ChatService:
    def __init__(
        self,
        flows_service=None,
        native_chat_agent=None,
        native_chat_history_service=None,
        session_ownership_service=None,
    ):
        self.flows_service = flows_service
        from services.native_chat_agent import NativeChatAgent
        from services.native_chat_history_service import NativeChatHistoryService
        from services.session_ownership_service import SessionOwnershipService

        if native_chat_history_service is None:
            from agent import conversation_persistence

            native_chat_history_service = NativeChatHistoryService(
                conversation_persistence._resolve_session_factory()
            )
        self.native_chat_history_service = native_chat_history_service
        self.session_ownership_service = session_ownership_service or SessionOwnershipService()
        self.native_chat_agent = native_chat_agent or NativeChatAgent(
            self.native_chat_history_service,
            self.session_ownership_service,
        )

    async def chat(
        self,
        prompt: str,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        stream: bool = False,
        filter_id: str = None,
        storage_user_id: str = None,
    ):
        """Handle chat requests with OpenRAG's native Python agent."""
        if not prompt:
            raise ValueError("Prompt is required")
        conversation_user_id = storage_user_id or user_id

        from config.settings import get_openrag_config

        config = get_openrag_config()
        agent_config = getattr(config, "agent", None)
        knowledge_config = getattr(config, "knowledge", None)
        logger.info(
            "[CHAT] Native OpenRAG chat request",
            stream=stream,
            continuing=bool(previous_response_id),
            prompt_chars=len(prompt),
            llm_provider=getattr(agent_config, "llm_provider", None),
            llm_model=getattr(agent_config, "llm_model", None),
            embedding_provider=getattr(knowledge_config, "embedding_provider", None),
            embedding_model=getattr(knowledge_config, "embedding_model", None),
        )

        # Set authentication context for this request so tools can access it
        if user_id and jwt_token:
            set_auth_context(user_id, jwt_token)

        if stream:
            return self.native_chat_agent.stream(
                prompt=prompt,
                user_id=conversation_user_id,
                previous_response_id=previous_response_id,
                filter_id=filter_id,
            )
        response_text, response_id, sources = await self.native_chat_agent.run(
            prompt=prompt,
            user_id=conversation_user_id,
            previous_response_id=previous_response_id,
            filter_id=filter_id,
        )
        response_data: dict[str, Any] = {"response": response_text, "response_id": response_id}
        if sources:
            response_data["sources"] = sources
        return response_data

    async def langflow_chat(
        self,
        prompt: str,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        conversation_id: str = None,
        stream: bool = False,
        filter_id: str = None,
        owner: str = None,
        owner_name: str = None,
        owner_email: str = None,
        storage_user_id: str = None,
    ):
        """Handle Langflow chat requests"""
        if not prompt:
            raise ValueError("Prompt is required")
        conversation_user_id = storage_user_id or user_id

        if DISABLE_CHAT_WITH_LANGFLOW:
            logger.info(
                "[CHAT] DISABLE_CHAT_WITH_LANGFLOW enabled; routing /langflow to native /chat"
            )
            native_previous_response_id = previous_response_id
            if (
                native_previous_response_id is None
                and conversation_id
                and await self.native_chat_history_service.owns_conversation(
                    conversation_id, conversation_user_id
                )
            ):
                native_previous_response_id = conversation_id
            return await self.chat(
                prompt,
                user_id,
                jwt_token,
                previous_response_id=native_previous_response_id,
                stream=stream,
                filter_id=filter_id,
                storage_user_id=storage_user_id,
            )

        if not LANGFLOW_URL or not LANGFLOW_CHAT_FLOW_ID:
            raise ValueError(
                "LANGFLOW_URL and LANGFLOW_CHAT_FLOW_ID environment variables are required"
            )

        # Prepare extra headers for JWT authentication and embedding model.
        # NOTE: extra_headers accumulates raw secrets (JWT, provider API keys —
        # see add_provider_credentials_to_headers below). Never log this dict or
        # pass it to a logger call (e.g. logger.info(..., extra_headers=...)).
        extra_headers = {}
        if jwt_token:
            extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token

        # Pass the selected embedding model as a global variable
        from config.settings import get_openrag_config
        from services.langflow_llm_token_service import HOP_PURPOSE_CHAT
        from utils.langflow_headers import (
            add_provider_credentials_to_headers,
            build_model_provider_headers,
        )

        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model
        embedding_provider = config.knowledge.embedding_provider or "openai"
        chunk_size = getattr(config.knowledge, "chunk_size", 1000)
        chunk_overlap = getattr(config.knowledge, "chunk_overlap", 200)
        extra_headers.update(build_model_provider_headers(config))

        # Configure ingest callback credentials/vars like ingestion does
        import uuid

        from config.settings import (
            LANGFLOW_INGEST_CALLBACK_BATCH_SIZE,
            get_index_name,
            get_ingest_callback_url,
        )
        from services.document_index_writer import DocumentIndexContext
        from services.langflow_ingest_token_service import LangflowIngestTokenService

        doc_id = str(uuid.uuid4())
        ingest_run_id = f"{doc_id}-{uuid.uuid4().hex}"
        context = DocumentIndexContext(
            document_id=doc_id,
            filename="",
            mimetype="",
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
            owner=owner,
            owner_name=owner_name,
            owner_email=owner_email,
            file_size=0,
            connector_type="url",
            source_url=None,
            allowed_users=[],
            allowed_groups=[],
            allowed_principals=[],
            allowed_principal_labels=[],
            ingest_run_id=ingest_run_id,
            is_sample_data=False,
            index_name=get_index_name(),
            parser="URL Ingester",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        token_service = LangflowIngestTokenService()
        ingest_token = token_service.create_token(context)

        extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_URL"] = get_ingest_callback_url()
        extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_TOKEN"] = ingest_token
        extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_RUN_ID"] = ingest_run_id
        extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_BATCH_SIZE"] = str(
            LANGFLOW_INGEST_CALLBACK_BATCH_SIZE
        )
        extra_headers["X-Langflow-Global-Var-CONNECTOR_TYPE"] = "url"

        # Add provider credentials to headers
        await add_provider_credentials_to_headers(
            extra_headers,
            config,
            flows_service=self.flows_service,
            jwt_token=jwt_token,
            user_id=user_id,
            purpose=HOP_PURPOSE_CHAT,
        )
        # Get context variables for filters, limit, and threshold
        from auth_context import (
            get_score_threshold,
            get_search_filters,
            get_search_limit,
        )

        filters = get_search_filters()
        limit = get_search_limit()
        score_threshold = get_score_threshold()

        # Build the complete filter expression like the search service does
        filter_expression: dict[str, Any] = {}
        if filters:
            filter_clauses = build_filter_clauses(filters)

            if filter_clauses:
                filter_expression["filter"] = filter_clauses

        # Add limit and score threshold to the filter expression (only if different from defaults)
        if limit and limit != 10:  # 10 is the default limit
            filter_expression["limit"] = limit

        if score_threshold and score_threshold != 0:  # 0 is the default threshold
            filter_expression["score_threshold"] = score_threshold

        # Pass the complete filter expression as a single header to Langflow (only if we have something to send)
        logger.info(
            "Sending OpenRAG query filter to Langflow",
            filter_expression=filter_expression,
        )
        extra_headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG-QUERY-FILTER"] = json.dumps(filter_expression)
        logger.info(
            "[CHAT] Langflow chat request", stream=stream, filters_applied=bool(filter_expression)
        )
        # Ensure the Langflow client exists; try lazy init if needed
        langflow_client = await clients.ensure_langflow_client()
        if not langflow_client:
            raise ValueError(
                "Langflow client not initialized. Ensure LANGFLOW is reachable or set LANGFLOW_KEY."
            )

        if stream:
            from agent import async_langflow_chat_stream

            return async_langflow_chat_stream(
                langflow_client,
                LANGFLOW_CHAT_FLOW_ID,
                prompt,
                conversation_user_id,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                filter_id=filter_id,
            )
        else:
            from agent import async_langflow_chat

            response_text, response_id, sources = await async_langflow_chat(
                langflow_client,
                LANGFLOW_CHAT_FLOW_ID,
                prompt,
                conversation_user_id,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                filter_id=filter_id,
            )
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            if sources:
                response_data["sources"] = sources
            return response_data

    async def langflow_nudges_chat(
        self,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        filters: dict = None,
        limit: int = None,
        score_threshold: float = None,
        storage_user_id: str = None,
    ):
        """Handle Langflow nudges chat requests with knowledge filters"""
        conversation_user_id = storage_user_id or user_id

        if not LANGFLOW_URL or not NUDGES_FLOW_ID:
            raise ValueError("LANGFLOW_URL and NUDGES_FLOW_ID environment variables are required")

        # Prepare extra headers for JWT authentication and embedding model.
        # NOTE: extra_headers accumulates raw secrets (JWT, provider API keys —
        # see add_provider_credentials_to_headers below). Never log this dict or
        # pass it to a logger call (e.g. logger.info(..., extra_headers=...)).
        extra_headers = {}
        if jwt_token:
            extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token

        from config.settings import get_openrag_config
        from services.langflow_llm_token_service import HOP_PURPOSE_CHAT
        from utils.langflow_headers import (
            add_provider_credentials_to_headers,
            build_model_provider_headers,
        )

        config = get_openrag_config()
        extra_headers.update(build_model_provider_headers(config))

        # Add provider credentials to headers
        await add_provider_credentials_to_headers(
            extra_headers,
            config,
            flows_service=self.flows_service,
            jwt_token=jwt_token,
            user_id=user_id,
            purpose=HOP_PURPOSE_CHAT,
        )

        # Build the complete filter expression like the chat service does
        filter_expression: dict[str, Any] = {}
        has_user_filters = False
        filter_clauses = build_filter_clauses(filters)

        if filters:
            if filter_clauses:
                has_user_filters = True

        # If no user filters are active, exclude sample data from nudges
        if not has_user_filters:
            # Add a bool query with must_not to exclude sample data
            filter_clauses.append({"bool": {"must_not": [{"term": {"is_sample_data": "true"}}]}})
            logger.info("Excluding sample data from nudges (no user filters active)")

        # Set the filter clauses if we have any
        if filter_clauses:
            filter_expression["filter"] = filter_clauses

        # Add limit and score threshold to the filter expression (only if different from defaults)
        if limit and limit != 10:  # 10 is the default limit
            filter_expression["limit"] = limit

        if score_threshold and score_threshold != 0:  # 0 is the default threshold
            filter_expression["score_threshold"] = score_threshold

        # Pass the complete filter expression as a single header to Langflow (only if we have something to send)
        extra_headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG-QUERY-FILTER"] = json.dumps(filter_expression)
        logger.info("[CHAT] Nudges request", filters_applied=bool(filter_expression))

        # Ensure the Langflow client exists; try lazy init if needed
        langflow_client = await clients.ensure_langflow_client()
        if not langflow_client:
            raise ValueError(
                "Langflow client not initialized. Ensure LANGFLOW is reachable or set LANGFLOW_KEY."
            )
        prompt = ""
        if previous_response_id:
            messages: list[dict[str, Any]] = []
            # Native history is scoped to the owner, including API-key storage identities.
            try:
                messages = await self.native_chat_history_service.messages_for(
                    previous_response_id, conversation_user_id
                )
            except Exception as e:
                logger.warning(f"Failed to fetch native messages for nudges: {e}")

            # Fall back to the legacy in-memory conversation.
            from agent import active_conversations

            if (
                not messages
                and conversation_user_id in active_conversations
                and previous_response_id in active_conversations[conversation_user_id]
            ):
                messages = active_conversations[conversation_user_id][previous_response_id].get(
                    "messages", []
                )

            # Filter out system messages
            user_ast_messages = [m for m in messages if m.get("role") in ["user", "assistant"]]

            # If no history in memory, try fetching from Langflow persistent history
            if not user_ast_messages:
                from services.langflow_history_service import langflow_history_service

                try:
                    lf_messages = await langflow_history_service.get_session_messages(
                        conversation_user_id, previous_response_id
                    )
                    if lf_messages:
                        messages = lf_messages
                        user_ast_messages = [
                            m for m in messages if m.get("role") in ["user", "assistant"]
                        ]
                except Exception as e:
                    logger.warning(f"Failed to fetch session messages for nudges: {e}")

            if user_ast_messages:
                # Return at max 8 messages (the last ones)
                user_ast_messages = user_ast_messages[-8:]

                formatted_messages = []

                def trim_results(r, depth=0):
                    MAX_DEPTH = 3
                    MAX_LIST_LEN = 3
                    MAX_DICT_KEYS = 5
                    MAX_STR_LEN = 1000

                    if isinstance(r, str):
                        return r[:MAX_STR_LEN] + ("..." if len(r) > MAX_STR_LEN else "")
                    elif isinstance(r, list):
                        if depth >= MAX_DEPTH:
                            return "[Max depth reached]"
                        return [trim_results(x, depth + 1) for x in r[:MAX_LIST_LEN]]
                    elif isinstance(r, dict):
                        if depth >= MAX_DEPTH:
                            return "[Max depth reached]"
                        trimmed = {}
                        for i, (k, v) in enumerate(r.items()):
                            if i >= MAX_DICT_KEYS:
                                trimmed["_more_keys"] = f"... ({len(r) - MAX_DICT_KEYS} omitted)"
                                break
                            trimmed[k] = trim_results(v, depth + 1)
                        return trimmed
                    return r

                for msg in user_ast_messages:
                    role = msg.get("role")
                    content = msg.get("content", "")
                    msg_str = f"{role}: {content}"

                    # Extract tool calls and chunks if this is an assistant message
                    if role == "assistant":
                        extracted_chunks = []

                        # 1. From chunks list
                        chunks = msg.get("chunks") or []
                        if isinstance(chunks, list):
                            last_tc = None
                            for chunk in chunks:
                                if isinstance(chunk, dict):
                                    item = chunk.get("item", {})
                                    if isinstance(item, dict) and item.get("type") in [
                                        "tool_call",
                                        "retrieval_call",
                                    ]:
                                        t_name = item.get("tool_name") or item.get("name") or "tool"
                                        res = trim_results(item.get("results"))
                                        tc = {"tool_name": t_name, "results": res}
                                        extracted_chunks.append(tc)
                                        last_tc = tc
                                    elif chunk.get("type") in [
                                        "response.tool_call.result",
                                        "tool_call_result",
                                    ]:
                                        res = trim_results(chunk.get("result") or chunk)
                                        if last_tc:
                                            last_tc["results"] = res
                                        else:
                                            extracted_chunks.append(
                                                {"tool_name": "tool", "results": res}
                                            )

                        # 2. From response_data dict/string
                        resp_data = msg.get("response_data")
                        if resp_data:
                            if isinstance(resp_data, str):
                                try:
                                    resp_data = json.loads(resp_data)
                                except Exception:
                                    resp_data = {}
                            if isinstance(resp_data, dict):
                                t_calls = resp_data.get("tool_calls") or []
                                if isinstance(t_calls, list):
                                    for tc in t_calls:
                                        if isinstance(tc, dict):
                                            t_name = tc.get("name")
                                            func = tc.get("function")
                                            if isinstance(func, dict) and not t_name:
                                                t_name = func.get("name")
                                            res = trim_results(tc.get("result"))
                                            extracted_chunks.append(
                                                {"tool_name": t_name or "tool", "results": res}
                                            )

                        if extracted_chunks:
                            chunks_strs = []
                            for tc in extracted_chunks:
                                t_name = tc.get("tool_name", "tool")
                                res = tc.get("results")
                                if res is not None:
                                    res_str = json.dumps(res, ensure_ascii=False, default=str)
                                    chunks_strs.append(f"[Tool: {t_name}, Results: {res_str}]")
                            if chunks_strs:
                                msg_str += "\nContext Chunks:\n" + "\n".join(chunks_strs)

                    formatted_messages.append(msg_str)

                prompt = "\n\n".join(formatted_messages)

        from agent import async_langflow_chat

        response_text, response_id, _sources = await async_langflow_chat(
            langflow_client,
            NUDGES_FLOW_ID,
            prompt,
            conversation_user_id,
            extra_headers=extra_headers,
            store_conversation=False,
        )
        response_data = {"response": response_text}
        if response_id:
            response_data["response_id"] = response_id
        return response_data

    async def upload_context_chat(
        self,
        document_content: str,
        filename: str,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        endpoint: str = "langflow",
        owner: str = None,
        owner_name: str = None,
        owner_email: str = None,
        storage_user_id: str = None,
    ):
        """Send document content as user message to get proper response_id"""
        document_prompt = (
            f"I'm uploading a document called '{filename}'. Here is its content:\n\n"
            f"{fence_untrusted_text(document_content)}\n\n"
            "Please confirm you've received this document and are ready to answer questions about it."
        )
        conversation_user_id = storage_user_id or user_id

        if endpoint == "langflow" and not DISABLE_CHAT_WITH_LANGFLOW:
            # Prepare extra headers for JWT authentication and embedding model.
            # NOTE: extra_headers accumulates raw secrets (JWT, provider API keys).
            # Never log this dict or pass it to a logger call
            # (e.g. logger.info(..., extra_headers=...)).
            extra_headers = {}
            if jwt_token:
                extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token

            from config.settings import get_openrag_config
            from services.langflow_llm_token_service import HOP_PURPOSE_CHAT
            from utils.langflow_headers import (
                add_provider_credentials_to_headers,
                build_model_provider_headers,
            )

            config = get_openrag_config()
            embedding_model = config.knowledge.embedding_model
            embedding_provider = config.knowledge.embedding_provider or "openai"
            chunk_size = getattr(config.knowledge, "chunk_size", 1000)
            chunk_overlap = getattr(config.knowledge, "chunk_overlap", 200)
            extra_headers.update(build_model_provider_headers(config))

            # Configure ingest callback credentials/vars like ingestion does
            import uuid

            from config.settings import (
                LANGFLOW_INGEST_CALLBACK_BATCH_SIZE,
                get_index_name,
                get_ingest_callback_url,
            )
            from services.document_index_writer import DocumentIndexContext
            from services.langflow_ingest_token_service import LangflowIngestTokenService

            doc_id = str(uuid.uuid4())
            ingest_run_id = f"{doc_id}-{uuid.uuid4().hex}"
            context = DocumentIndexContext(
                document_id=doc_id,
                filename="",
                mimetype="",
                embedding_model=embedding_model,
                embedding_provider=embedding_provider,
                owner=owner,
                owner_name=owner_name,
                owner_email=owner_email,
                file_size=0,
                connector_type="url",
                source_url=None,
                allowed_users=[],
                allowed_groups=[],
                allowed_principals=[],
                allowed_principal_labels=[],
                ingest_run_id=ingest_run_id,
                is_sample_data=False,
                index_name=get_index_name(),
                parser="URL Ingester",
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            token_service = LangflowIngestTokenService()
            ingest_token = token_service.create_token(context)

            extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_URL"] = get_ingest_callback_url()
            extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_TOKEN"] = ingest_token
            extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_RUN_ID"] = ingest_run_id
            extra_headers["X-Langflow-Global-Var-OPENRAG_INGEST_BATCH_SIZE"] = str(
                LANGFLOW_INGEST_CALLBACK_BATCH_SIZE
            )
            extra_headers["X-Langflow-Global-Var-CONNECTOR_TYPE"] = "url"

            # Add provider credentials to headers
            await add_provider_credentials_to_headers(
                extra_headers,
                config,
                flows_service=self.flows_service,
                jwt_token=jwt_token,
                user_id=user_id,
                purpose=HOP_PURPOSE_CHAT,
            )

            # Ensure the Langflow client exists; try lazy init if needed
            langflow_client = await clients.ensure_langflow_client()
            if not langflow_client:
                raise ValueError(
                    "Langflow client not initialized. Ensure LANGFLOW is reachable or set LANGFLOW_KEY."
                )

            response_text, response_id = await async_langflow(
                langflow_client=langflow_client,
                flow_id=LANGFLOW_CHAT_FLOW_ID,
                prompt=document_prompt,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
            )
        else:  # native chat
            response = await self.chat(
                document_prompt,
                user_id,
                jwt_token,
                previous_response_id=previous_response_id,
                storage_user_id=conversation_user_id,
            )
            response_text, response_id = response["response"], response["response_id"]

        return response_text, response_id

    async def get_chat_history(self, user_id: str):
        """Get durable native-agent history (never Langflow messages)."""
        if not user_id:
            return {"error": "User ID is required", "conversations": []}
        return await self.native_chat_history_service.history(user_id)

    async def delete_session(self, user_id: str, session_id: str):
        """Delete a session from both local storage and Langflow"""
        if DISABLE_CHAT_WITH_LANGFLOW and await self.native_chat_history_service.owns_conversation(
            session_id, user_id
        ):
            deleted = await self.native_chat_history_service.delete(session_id, user_id)
            if deleted:
                await self.session_ownership_service.release_session(user_id, session_id)
            return {
                "success": deleted,
                "not_found": not deleted,
                "local_deleted": deleted,
                "langflow_deleted": False,
                "error": None if deleted else "Conversation not found",
            }
        try:
            # Resolve the complete, owned group before removing any associations.
            from agent import delete_user_conversation
            from services.session_ownership_service import session_ownership_service

            session_ids = await session_ownership_service.get_conversation_sessions(
                user_id, session_id
            )

            # Attempt every upstream deletion first: local revocation failures
            # must not erase JSON-only aliases before their cleanup is attempted.
            upstream_results = [
                await self._delete_langflow_session(owned_id) for owned_id in session_ids
            ]
            langflow_deleted = bool(upstream_results) and all(upstream_results)

            local_deleted = await delete_user_conversation(
                user_id, session_id, session_ids=session_ids
            )

            if not local_deleted:
                return {
                    "success": False,
                    "not_found": True,
                    "error": "Conversation not found",
                }

            return {
                "success": True,
                "local_deleted": local_deleted,
                "langflow_deleted": langflow_deleted,
                "error": None,
            }

        except Exception as e:
            logger.error(f"Error deleting session {session_id} for user {user_id}: {e}")
            return {"success": False, "error": str(e)}

    async def delete_sessions(self, user_id: str, session_ids: list[str]) -> dict[str, list[str]]:
        """Best-effort bulk delete, any failures are returned in response + logged

        Returns {"deleted": [ids], "failed": [ids]}.
        """
        from services.session_ownership_service import session_ownership_service

        deleted: list[str] = []
        failed: list[str] = []

        for session_id in dict.fromkeys(session_ids):
            try:
                owner = await session_ownership_service.get_session_owner(session_id)
                if owner is not None and owner != user_id:
                    logger.warning("bulk_delete: %s not owned by %s", session_id, user_id)
                    failed.append(session_id)
                    continue

                result = await self.delete_session(user_id, session_id)
                if result.get("success"):
                    deleted.append(session_id)
                else:
                    logger.warning("bulk_delete: %s error: %s", session_id, result.get("error"))
                    failed.append(session_id)
            except Exception:
                logger.exception("bulk_delete: %s unexpected error", session_id)
                failed.append(session_id)

        return {"deleted": deleted, "failed": failed}

    async def _delete_langflow_session(self, session_id: str):
        """Delete a session from Langflow using the monitor API"""
        try:
            response = await clients.langflow_request(
                "DELETE", f"/api/v1/monitor/messages/session/{session_id}"
            )

            if response.status_code == 200 or response.status_code == 204:
                logger.info(f"Successfully deleted session {session_id} from Langflow")
                return True
            else:
                logger.warning(
                    f"Failed to delete session {session_id} from Langflow: "
                    f"{response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error deleting session {session_id} from Langflow: {e}")
            return False

    async def delete_all_user_sessions(self, user_id: str):
        """Delete all sessions for a user from both local storage and Langflow"""
        from agent import get_user_conversations

        native_deleted_count = 0
        if DISABLE_CHAT_WITH_LANGFLOW:
            native_session_ids = await self.native_chat_history_service.conversation_ids(user_id)
            native_deleted_count = await self.native_chat_history_service.delete_all(user_id)
            await self.session_ownership_service.release_conversation_sessions(
                user_id, native_session_ids
            )
        conversations = await get_user_conversations(user_id)
        session_ids = list(conversations.keys())

        results = []
        for session_id in session_ids:
            result = await self.delete_session(user_id, session_id)
            results.append(result)

        langflow_deleted_count = len([r for r in results if r.get("success")])
        if not DISABLE_CHAT_WITH_LANGFLOW:
            return {
                "success": True,
                "deleted_count": langflow_deleted_count,
                "total_count": len(session_ids),
            }
        return {
            "success": True,
            "deleted_count": native_deleted_count + langflow_deleted_count,
            "total_count": native_deleted_count + len(session_ids),
            "native_deleted_count": native_deleted_count,
            "langflow_deleted_count": langflow_deleted_count,
        }
