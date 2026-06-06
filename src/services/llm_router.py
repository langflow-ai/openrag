"""
LLM Router — provider-agnostic interface for LLM completion calls.

Phase 2: Ollama backend (uses existing OLLAMA_ENDPOINT infrastructure).
Phase 3: Set GRANITE_BACKEND=sglang to enable SGLang backend (RadixAttention,
         Zero-Overhead Scheduler — 3.1x faster than vLLM on MoE models).

Usage:
    from services.llm_router import llm_router

    response = await llm_router.complete(
        prompt="Explain retrieval-augmented generation in one paragraph.",
        system_prompt="You are a concise technical assistant.",
    )

Required env vars (when GRANITE_BACKEND=ollama, the default):
    OLLAMA_ENDPOINT   — Ollama server URL (e.g. http://localhost:11434)
    GRANITE_MODEL     — Model name in Ollama registry (default: granite4.1:3b)

Optional env vars:
    GRANITE_ENDPOINT  — Override endpoint (bypasses OLLAMA_ENDPOINT lookup)
    GRANITE_BACKEND   — "ollama" (default) | "sglang" (Phase 3)
"""

import os
from typing import Optional

import httpx

from config.settings import GRANITE_BACKEND, GRANITE_ENDPOINT, GRANITE_MODEL
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LLMRouter:
    """
    Routes LLM completion calls to the configured backend.

    Backends
    --------
    ollama  : Ollama REST API (/api/chat). Active for Phase 2.
    sglang  : SGLang server. Reserved for Phase 3 — raises NotImplementedError
              until the SGLang service is deployed.

    The backend is selected by the GRANITE_BACKEND env var (default: "ollama").
    Use the module-level ``llm_router`` singleton rather than instantiating directly.
    """

    def __init__(self) -> None:
        self._backend: str = GRANITE_BACKEND
        self._http_client: Optional[httpx.AsyncClient] = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._http_client

    def _resolve_endpoint(self) -> str:
        """Resolve the LLM endpoint, falling back through the config hierarchy."""
        if GRANITE_ENDPOINT:
            return GRANITE_ENDPOINT

        # Try config manager first (dynamic provider config)
        try:
            from config.settings import config_manager
            from utils.container_utils import transform_localhost_url

            cfg = config_manager.get_config()
            if cfg and cfg.providers.ollama.endpoint:
                return transform_localhost_url(cfg.providers.ollama.endpoint)
        except Exception:
            pass

        # Fall back to env var
        from utils.container_utils import transform_localhost_url

        return transform_localhost_url(
            os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        )

    async def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        """
        Single-turn LLM completion. Returns the response text.

        Parameters
        ----------
        prompt       : User message content.
        model        : Override the model name (defaults to GRANITE_MODEL env var).
        system_prompt: Optional system message prepended to the conversation.
        temperature  : Sampling temperature (default 0.1 for deterministic outputs).
        max_tokens   : Maximum tokens in the response (default 2048).

        Raises
        ------
        httpx.HTTPError      : On network or HTTP-level failures.
        NotImplementedError  : If GRANITE_BACKEND is set to an unimplemented value.
        """
        model = model or GRANITE_MODEL

        if self._backend == "ollama":
            return await self._ollama_complete(
                prompt, model, system_prompt, temperature, max_tokens
            )

        if self._backend == "sglang":
            raise NotImplementedError(
                "SGLang backend is reserved for Phase 3. "
                "Set GRANITE_BACKEND=ollama or deploy the SGLang service first."
            )

        raise NotImplementedError(f"Unknown backend: '{self._backend}'")

    async def _ollama_complete(
        self,
        prompt: str,
        model: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> str:
        endpoint = self._resolve_endpoint()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        logger.debug(
            "LLMRouter: Ollama request",
            model=model,
            endpoint=endpoint,
        )

        client = self._get_http_client()
        response = await client.post(f"{endpoint}/api/chat", json=payload)
        response.raise_for_status()

        data = response.json()
        text = data.get("message", {}).get("content", "")

        logger.debug("LLMRouter: Ollama response received", chars=len(text))
        return text

    async def cleanup(self) -> None:
        """Close the shared HTTP client. Call on application shutdown."""
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
                logger.info("LLMRouter HTTP client closed")
            except Exception as e:
                logger.warning("LLMRouter cleanup error", error=str(e))
            finally:
                self._http_client = None


# Module-level singleton — import this directly
llm_router = LLMRouter()
