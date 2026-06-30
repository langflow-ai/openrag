from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import (
    HandleInput,
    IntInput,
    Output,
    StrInput,
    TableInput,
)
from lfx.schema.dataframe import DataFrame
from lfx.log import logger
from lfx.schema.data import Data

REQUEST_TIMEOUT = 60

_WATSONX_RATE_LIMIT_HEADERS = (
    "x-requests-limit-rate",
    "x-requests-limit-remaining",
    "x-requests-limit-reset",
    "Retry-After",
)


def _log_watsonx_rate_limit_headers(error: Exception) -> None:
    """Log watsonx rate-limit headers from a failed embedding call for operator diagnostics."""
    try:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return
        status = getattr(response, "status_code", "unknown")
        observed = {h: headers.get(h) for h in _WATSONX_RATE_LIMIT_HEADERS if headers.get(h) is not None}
        if str(status) == "429" or observed:
            logger.warning(f"watsonx rate-limit response (status={status}): {observed}")
    except Exception as log_error:
        logger.debug(f"Could not extract watsonx rate-limit headers: {log_error}")


def normalize_model_name(model_name: str) -> str:
    """Normalize embedding model name to a valid OpenSearch field name suffix."""
    normalized = model_name.lower()
    normalized = normalized.replace("-", "_").replace(":", "_").replace("/", "_").replace(".", "_")
    normalized = "".join(c if c.isalnum() or c == "_" else "_" for c in normalized)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def get_embedding_field_name(model_name: str) -> str:
    """Return the dynamic OpenSearch field name for the given embedding model."""
    field = f"chunk_embedding_{normalize_model_name(model_name)}"
    logger.info(field)
    return field


class OpenSearchOpenRAGComponent(Component):
    """OpenRAG Ingest Component — embed documents and POST to the OpenRAG backend callback.

    No direct OpenSearch connection is needed. The backend owns the index write path;
    this component only generates vectors and feeds them to the backend via HTTP.
    Search is handled by the separate OpenSearch (Multi-Model) component.
    """

    display_name: str = "OpenSearch (OpenRAG Ingest)"
    icon: str = "OpenSearch"
    description: str = (
        "Embed documents and send them to the OpenRAG backend ingest callback. "
        "No direct OpenSearch credentials are required — the backend owns the index write path."
    )

    _openrag_ingest_global_placeholders = {
        "openrag_ingest_url": "OPENRAG_INGEST_URL",
        "openrag_ingest_token": "OPENRAG_INGEST_TOKEN",
        "openrag_ingest_run_id": "OPENRAG_INGEST_RUN_ID",
    }

    inputs = [
        TableInput(
            name="docs_metadata",
            display_name="Document Metadata",
            info=(
                "Additional metadata key-value pairs added to all ingested documents. "
                "Useful for tagging with source information, categories, or other attributes."
            ),
            table_schema=[
                {"name": "key", "display_name": "Key", "type": "str", "description": "Key name"},
                {"name": "value", "display_name": "Value", "type": "str", "description": "Value"},
            ],
            value=[],
            input_types=["Data", "JSON"],
        ),
        HandleInput(
            name="ingest_data",
            display_name="Ingest Data",
            input_types=["Data", "DataFrame", "Table"],
            is_list=True,
        ),
        HandleInput(
            name="embedding",
            display_name="Embedding",
            input_types=["Embeddings"],
            is_list=True,
        ),
        StrInput(
            name="embedding_model_name",
            display_name="Embedding Model Name",
            value="",
            info=(
                "Name of the embedding model to use for ingestion. Matches on deployment, model, "
                "model_id, or model_name. For duplicate deployments use 'deployment:model'. "
                "Leave empty to use the first embedding."
            ),
            advanced=False,
        ),
        StrInput(
            name="openrag_ingest_url",
            display_name="OpenRAG Ingest URL",
            value="OPENRAG_INGEST_URL",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
            info="Internal OpenRAG callback URL for backend-owned document indexing.",
        ),
        StrInput(
            name="openrag_ingest_token",
            display_name="OpenRAG Ingest Token",
            value="OPENRAG_INGEST_TOKEN",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
            info="Short-lived token used only for OpenRAG ingest callbacks.",
        ),
        StrInput(
            name="openrag_ingest_run_id",
            display_name="OpenRAG Ingest Run ID",
            value="OPENRAG_INGEST_RUN_ID",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
        ),
        IntInput(
            name="openrag_ingest_batch_size",
            display_name="OpenRAG Ingest Batch Size",
            value=100,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Ingest Result",
            name="ingest_result",
            method="run_ingest",
        ),
    ]

    # ---------- OpenRAG callback helpers ----------

    @staticmethod
    def _openrag_input_to_str(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        if hasattr(value, "text"):
            value = value.text
        return str(value or "").strip()

    def _openrag_callback_value(self, attr_name: str) -> str:
        value = self._openrag_input_to_str(getattr(self, attr_name, ""))
        if value == self._openrag_ingest_global_placeholders.get(attr_name):
            return ""
        return value

    def _openrag_ingest_callback_config(self) -> tuple[str, str, str] | None:
        url = self._openrag_callback_value("openrag_ingest_url")
        token = self._openrag_callback_value("openrag_ingest_token")
        ingest_run_id = self._openrag_callback_value("openrag_ingest_run_id")

        masked_token = (
            f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else ("<set>" if token else "")
        )
        debug_payload = {
            "openrag_ingest_url": url,
            "openrag_ingest_url_len": len(url),
            "openrag_ingest_token_masked": masked_token,
            "openrag_ingest_token_len": len(token),
            "openrag_ingest_run_id": ingest_run_id,
            "raw_url_type": type(self.openrag_ingest_url).__name__,
            "raw_token_type": type(self.openrag_ingest_token).__name__,
            "raw_run_id_type": type(self.openrag_ingest_run_id).__name__,
        }
        logger.warning(f"[OpenRAG callback config] {debug_payload}")
        try:
            self.log(f"[OpenRAG callback config] {debug_payload}")
        except Exception:
            pass

        if not url and not token and not ingest_run_id:
            return None
        if not url or not token or not ingest_run_id:
            msg = "OpenRAG ingest callback requires url, token, and ingest_run_id."
            raise ValueError(msg)
        return url, token, ingest_run_id

    def _post_openrag_ingest_batches(
        self,
        *,
        requests: list[dict],
        vector_field: str,
        text_field: str,
    ) -> None:
        callback_config = self._openrag_ingest_callback_config()
        if callback_config is None:
            return

        url, token, ingest_run_id = callback_config
        batch_size = max(self._parse_int_param("openrag_ingest_batch_size", 100), 1)
        timeout = self._parse_int_param("request_timeout", REQUEST_TIMEOUT)
        headers = {"Authorization": f"Bearer {token}"}

        masked_token = (
            f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else ("<set>" if token else "")
        )
        request_summary = {
            "url": url,
            "ingest_run_id": ingest_run_id,
            "token_masked": masked_token,
            "total_chunks": len(requests),
            "batch_size": batch_size,
            "timeout_s": timeout,
        }
        logger.warning(f"[OpenRAG ingest POST] {request_summary}")
        try:
            self.log(f"[OpenRAG ingest POST] {request_summary}")
        except Exception:
            pass

        with httpx.Client(timeout=timeout) as client:
            total_batches = (len(requests) + batch_size - 1) // batch_size
            for batch_number, start in enumerate(range(0, len(requests), batch_size), start=1):
                batch = requests[start : start + batch_size]
                final = batch_number == total_batches
                payload = {
                    "ingest_run_id": ingest_run_id,
                    "batch_id": batch_number,
                    "final": final,
                    "chunks": [
                        self._openrag_chunk_payload(
                            request,
                            vector_field=vector_field,
                            text_field=text_field,
                        )
                        for request in batch
                    ],
                }
                logger.warning(
                    f"[OpenRAG ingest POST] -> batch={batch_number}/{total_batches} "
                    f"url={url} chunks={len(payload['chunks'])} final={final}"
                )
                response = client.post(url, json=payload, headers=headers)
                response_summary = {
                    "batch": batch_number,
                    "url": url,
                    "status": response.status_code,
                    "final_url": str(response.request.url),
                    "response_headers": dict(response.headers),
                    "body_preview": response.text[:500],
                }
                logger.warning(f"[OpenRAG ingest POST resp] {response_summary}")
                try:
                    self.log(f"[OpenRAG ingest POST resp] {response_summary}")
                except Exception:
                    pass
                if response.status_code >= 400:
                    msg = (
                        "OpenRAG ingest callback failed "
                        f"(batch={batch_number}, status={response.status_code}, "
                        f"url={url}): {response.text[:1000]}"
                    )
                    raise RuntimeError(msg)

        self.log(f"Posted {len(requests)} chunks to OpenRAG backend ingest callback.")

    @staticmethod
    def _openrag_chunk_payload(
        request: dict,
        *,
        vector_field: str,
        text_field: str,
    ) -> dict:
        metadata = {
            key: value
            for key, value in request.items()
            if key not in {"_op_type", "_index", "_id", "id", vector_field, text_field}
        }
        page = metadata.get("page")
        if isinstance(page, str) and page.isdigit():
            page = int(page)
        return {
            "id": request.get("_id") or request.get("id"),
            "text": request.get(text_field, ""),
            "vector": request[vector_field],
            "page": page if isinstance(page, int) else None,
            "metadata": metadata,
        }

    # ---------- param helper ----------

    def _parse_int_param(self, attr_name: str, default: int) -> int:
        raw = getattr(self, attr_name, None)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            value = int(str(raw).strip())
        except ValueError:
            logger.warning(f"Invalid integer value '{raw}' for {attr_name}, using default {default}")
            return default
        if value < 0:
            logger.warning(f"Negative value '{raw}' for {attr_name}, using default {default}")
            return default
        return value

    # ---------- embedding helpers ----------

    def _get_embedding_model_name(self, embedding_obj=None) -> str:
        """Resolve the embedding model name; priority: deployment > model > model_id > model_name."""
        if hasattr(self, "embedding_model_name") and self.embedding_model_name:
            return self.embedding_model_name.strip()
        target = embedding_obj
        if target is None and hasattr(self, "embedding") and self.embedding:
            target = self.embedding[0] if isinstance(self.embedding, list) else self.embedding
        if target:
            for attr in ("deployment", "model", "model_id", "model_name"):
                val = getattr(target, attr, None)
                if val:
                    return str(val)
        msg = (
            "Could not determine embedding model name. "
            "Please set 'embedding_model_name' or ensure the embedding component "
            "has a 'deployment', 'model', 'model_id', or 'model_name' attribute."
        )
        raise ValueError(msg)

    # ---------- ingest ----------

    def _prepare_ingest_data(self) -> list:
        ingest_data = self.ingest_data
        if not ingest_data:
            return []
        if not isinstance(ingest_data, list):
            ingest_data = [ingest_data]
        result = []
        for item in ingest_data:
            if isinstance(item, DataFrame):
                result.extend(item.to_data_list())
            else:
                result.append(item)
        return result

    def _add_documents_to_vector_store(self) -> int:
        """Embed all ingest documents and POST them to the OpenRAG backend callback.

        Returns:
            Number of document chunks sent to the callback.
        """
        self.ingest_data = self._prepare_ingest_data()
        docs = self.ingest_data or []
        if not docs:
            logger.debug("[OpenRAGIngest] No documents to ingest.")
            return 0

        if not self.embedding:
            msg = "Embedding handle is required to embed documents."
            raise ValueError(msg)

        embeddings_list = self.embedding if isinstance(self.embedding, list) else [self.embedding]
        embeddings_list = [e for e in embeddings_list if e is not None]
        if not embeddings_list:
            logger.warning("[OpenRAGIngest] All embeddings returned None (fail-safe mode). Skipping.")
            self.log("Embedding returned None (fail-safe mode). Skipping ingest.")
            return 0

        # --- Select embedding for ingestion ---
        selected_embedding = None
        embedding_model = None

        if hasattr(self, "embedding_model_name") and self.embedding_model_name.strip():
            target_model_name = self.embedding_model_name.strip()
            self.log(f"Looking for embedding model: {target_model_name}")

            for emb_obj in embeddings_list:
                possible_names = []
                deployment = getattr(emb_obj, "deployment", None)
                model = getattr(emb_obj, "model", None)
                model_id = getattr(emb_obj, "model_id", None)
                model_name = getattr(emb_obj, "model_name", None)
                available_models_attr = getattr(emb_obj, "available_models", None)

                if deployment:
                    possible_names.append(str(deployment))
                if model:
                    possible_names.append(str(model))
                if model_id:
                    possible_names.append(str(model_id))
                if model_name:
                    possible_names.append(str(model_name))
                if deployment and model and deployment != model:
                    possible_names.append(f"{deployment}:{model}")
                if available_models_attr and isinstance(available_models_attr, dict):
                    possible_names.extend(
                        str(k).strip() for k in available_models_attr if k and str(k).strip()
                    )

                if target_model_name in possible_names:
                    if (
                        available_models_attr
                        and isinstance(available_models_attr, dict)
                        and target_model_name in available_models_attr
                    ):
                        selected_embedding = available_models_attr[target_model_name]
                        embedding_model = target_model_name
                        self.log(f"Found dedicated embedding instance for '{embedding_model}' in available_models")
                    else:
                        selected_embedding = emb_obj
                        embedding_model = self._get_embedding_model_name(emb_obj)
                        self.log(f"Found embedding model: {embedding_model} (matched '{target_model_name}')")
                    break

            if not selected_embedding:
                available_info = []
                for idx, emb in enumerate(embeddings_list):
                    identifiers = []
                    for attr in ("deployment", "model", "model_id", "model_name"):
                        val = getattr(emb, attr, None)
                        if val:
                            identifiers.append(f"{attr}='{val}'")
                    available_models_attr = getattr(emb, "available_models", None)
                    if available_models_attr and isinstance(available_models_attr, dict):
                        identifiers.append(f"available_models={list(available_models_attr.keys())}")
                    available_info.append(
                        f"  [{idx}] {type(emb).__name__}: "
                        + (", ".join(identifiers) or "No identifiers")
                    )
                msg = (
                    f"Embedding model '{target_model_name}' not found in available embeddings.\n\n"
                    f"Available embeddings:\n" + "\n".join(available_info) + "\n\n"
                    "Set 'embedding_model_name' to one of the identifier values shown above."
                )
                raise ValueError(msg)
        else:
            selected_embedding = embeddings_list[0]
            embedding_model = self._get_embedding_model_name(selected_embedding)
            self.log(f"No embedding_model_name specified, using first embedding: {embedding_model}")

        dynamic_field_name = get_embedding_field_name(embedding_model)
        self.log(f"Using embedding model: {embedding_model}, field: {dynamic_field_name}")

        # --- Extract texts and metadata ---
        additional_metadata: dict = {}
        logger.debug(f"[OpenRAGIngest] docs_metadata: {self.docs_metadata}")
        if hasattr(self, "docs_metadata") and self.docs_metadata:
            if isinstance(self.docs_metadata[-1], Data):
                self.docs_metadata = self.docs_metadata[-1].data
                additional_metadata.update(self.docs_metadata)
            else:
                for item in self.docs_metadata:
                    if isinstance(item, dict) and "key" in item and "value" in item:
                        additional_metadata[item["key"]] = item["value"]
        for key, value in additional_metadata.items():
            if value == "None":
                additional_metadata[key] = None
        logger.info(f"[OpenRAGIngest] Additional metadata: {additional_metadata}")

        texts: list[str] = []
        metadatas: list[dict] = []
        for doc_obj in docs:
            data_copy = json.loads(doc_obj.model_dump_json())
            text = data_copy.pop(doc_obj.text_key, doc_obj.default_value)
            texts.append(text)
            data_copy.update(additional_metadata)
            metadatas.append(data_copy)

        # --- Generate vectors (watsonx SDK-managed vs tenacity-retry parallel) ---
        is_ibm = (embedding_model and "ibm" in str(embedding_model).lower()) or (
            selected_embedding and "watsonx" in type(selected_embedding).__name__.lower()
        )
        logger.debug(f"[OpenRAGIngest] is_ibm={is_ibm}")

        if is_ibm:
            logger.info(
                f"[OpenRAGIngest] Embedding {len(texts)} chunks via watsonx SDK "
                "(SDK-managed throttle + 429 retry)"
            )
            try:
                vectors: list[list[float]] = selected_embedding.embed_documents(texts)
                logger.info(f"[OpenRAGIngest] Embedded {len(vectors)} chunks via watsonx SDK")
            except Exception as embed_error:
                _log_watsonx_rate_limit_headers(embed_error)
                logger.error(f"[OpenRAGIngest] watsonx embed failed: {embed_error}")
                raise
        else:
            from tenacity import (
                retry,
                retry_if_exception,
                stop_after_attempt,
                wait_exponential,
            )

            def is_rate_limit_error(exception: Exception) -> bool:
                error_str = str(exception).lower()
                return "429" in error_str or "rate_limit" in error_str or "rate limit" in error_str

            def is_other_retryable_error(exception: Exception) -> bool:
                if is_rate_limit_error(exception):
                    return False
                return isinstance(exception, (ConnectionError, TimeoutError, OSError))

            retry_on_rate_limit = retry(
                retry=retry_if_exception(is_rate_limit_error),
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=2, min=2, max=30),
                reraise=True,
                before_sleep=lambda retry_state: logger.warning(
                    f"Rate limit hit (attempt {retry_state.attempt_number}/5), "
                    f"backing off {retry_state.next_action.sleep:.1f}s"
                ),
            )
            retry_on_other_errors = retry(
                retry=retry_if_exception(is_other_retryable_error),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                reraise=True,
                before_sleep=lambda retry_state: logger.warning(
                    f"Embed error (attempt {retry_state.attempt_number}/3): "
                    f"{retry_state.outcome.exception()}"
                ),
            )

            def embed_chunk_with_retry(chunk_text: str, chunk_idx: int) -> list[float]:
                @retry_on_rate_limit
                @retry_on_other_errors
                def _embed(text: str) -> list[float]:
                    return selected_embedding.embed_documents([text])[0]

                try:
                    return _embed(chunk_text)
                except Exception as e:
                    logger.error(f"[OpenRAGIngest] Failed to embed chunk {chunk_idx}: {e}")
                    raise

            vectors = [None] * len(texts)
            max_workers = min(max(len(texts), 1), 8)
            logger.debug(f"[OpenRAGIngest] Parallel embedding with {max_workers} workers")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(embed_chunk_with_retry, chunk, idx): idx
                    for idx, chunk in enumerate(texts)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    vectors[idx] = future.result()

        if not vectors:
            self.log(f"No vectors generated for model {embedding_model}.")
            return 0

        # --- Build request dicts ---
        vector_dimensions = len(vectors[0]) if vectors else None
        requests: list[dict] = []

        for i, text in enumerate(texts):
            metadata = dict(metadatas[i]) if metadatas else {}
            if vector_dimensions is not None and "embedding_dimensions" not in metadata:
                metadata["embedding_dimensions"] = vector_dimensions

            # Normalize ACL fields that may arrive as JSON strings from flows
            for acl_key in ("allowed_users", "allowed_groups", "allowed_principals"):
                acl_value = metadata.get(acl_key)
                if isinstance(acl_value, str):
                    try:
                        parsed = json.loads(acl_value)
                        if isinstance(parsed, list):
                            metadata[acl_key] = parsed
                    except (json.JSONDecodeError, TypeError):
                        pass

            metadata_document_id = str(metadata.get("document_id") or "").strip()
            if metadata_document_id and metadata_document_id.lower() != "none":
                _id = f"{metadata_document_id}_{i}"
            else:
                _id = str(uuid.uuid4())

            requests.append({
                "_id": _id,
                dynamic_field_name: vectors[i],
                "text": text,
                "embedding_model": embedding_model,
                **metadata,
            })

        # --- POST to OpenRAG callback ---
        callback_config = self._openrag_ingest_callback_config()
        if callback_config is None:
            self.log("No OpenRAG ingest callback configured — skipping ingest.")
            return 0

        self._post_openrag_ingest_batches(
            requests=requests,
            vector_field=dynamic_field_name,
            text_field="text",
        )
        logger.info(
            f"[OpenRAGIngest] Sent {len(requests)} chunks for model '{embedding_model}'"
        )
        self.log(f"Successfully sent {len(requests)} chunks for model '{embedding_model}'.")
        return len(requests)

    def run_ingest(self) -> Data:
        """Embed documents and POST chunks to the OpenRAG backend ingest callback."""
        try:
            n = self._add_documents_to_vector_store()
            run_id = self._openrag_callback_value("openrag_ingest_run_id")
            return Data(data={"status": "ok", "docs_indexed": n, "ingest_run_id": run_id})
        except Exception as e:
            self.log(f"run_ingest error: {e}")
            raise
