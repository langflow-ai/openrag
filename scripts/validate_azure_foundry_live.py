#!/usr/bin/env python3
"""Live validation matrix for the Azure AI Foundry provider.

Runs the checks that must pass against a **real Foundry resource** before
`azure_ai` is made visible in any run mode. Everything here is deliberately
read through OpenRAG's own code — `enhancements.providers.azure.foundry`,
`services.llm_gateway`, `services.docling_service` — rather than reimplemented
with `curl`-equivalent requests. A script that built its own URLs would prove
Azure works, not that OpenRAG calls it correctly, which is the open question.

The provider stays hidden while this runs. Nothing here reads
`model_providers.yaml` or the saved configuration: credentials come from the
environment and a config object is assembled in memory, so the matrix can be
run against production code with the feature still switched off.

Usage
-----
    export AZURE_AI_API_BASE="https://<resource>.services.ai.azure.com/openai/v1"
    export AZURE_AI_API_KEY="<key>"
    export AZURE_AI_CHAT_DEPLOYMENT="<your chat deployment>"
    export AZURE_AI_EMBEDDING_DEPLOYMENT="<your embedding deployment>"

    # Optional, each unlocks more of the matrix:
    export AZURE_AI_PROJECT_API_BASE="https://<r>.services.ai.azure.com/api/projects/<p>/openai/v1"
    export AZURE_AI_LEGACY_API_BASE="https://<resource>.services.ai.azure.com/models"
    export AZURE_AI_VLM_DEPLOYMENT="<a vision-capable deployment>"

    uv run python scripts/validate_azure_foundry_live.py

Exit code is non-zero if any **blocker** fails. Blockers are the capabilities
the product claims once the provider is visible: supported endpoint routing,
chat, streaming, tool calling, embeddings, Docling VLM, and error
sanitization. Cost attribution is reported but never blocks — OpenRAG does not
consume cost data today (see the transport trade-off in `foundry.py`).

The API key is never printed. Every captured error and log line is scanned for
it at the end, and check 11 fails if it appears anywhere.

What this cannot cover
----------------------
Check 10 exercises the exact URL, headers and params OpenRAG hands
docling-serve, by issuing that request itself. It does not run docling-serve.
Before the flip, also do one real ingest of an image-bearing document through
the running stack with picture descriptions enabled, to confirm docling-serve
accepts the block as given.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for path in (str(SRC), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


# --------------------------------------------------------------------------
# Result collection
# --------------------------------------------------------------------------

BLOCKER = "blocker"
ADVISORY = "advisory"


@dataclass
class Check:
    number: int
    name: str
    severity: str
    status: str = "skipped"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("pass", "skipped")


@dataclass
class Matrix:
    checks: list[Check] = field(default_factory=list)
    #: Everything the run produced that a secret could hide in.
    captured_text: list[str] = field(default_factory=list)

    def record(self, number: int, name: str, severity: str, status: str, detail: str = "") -> Check:
        check = Check(number, name, severity, status, detail)
        self.checks.append(check)
        self.captured_text.append(detail)
        return check

    def capture(self, text: str) -> None:
        self.captured_text.append(text)


def _describe_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# In-memory config, so nothing depends on the provider being enabled or saved
# --------------------------------------------------------------------------


def _build_config(api_base: str, api_key: str, chat_model: str, embedding_model: str):
    from config.config_manager import (
        AnthropicConfig,
        GenericProviderConfig,
        OllamaConfig,
        OpenAIConfig,
        ProvidersConfig,
        WatsonXConfig,
    )

    providers = ProvidersConfig(
        openai=OpenAIConfig(),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={
            "azure_ai": GenericProviderConfig(
                credentials={"api_base": api_base, "api_key": api_key},
                configured=True,
            )
        },
    )
    return SimpleNamespace(
        providers=providers,
        agent=SimpleNamespace(llm_model=chat_model, llm_provider="azure_ai"),
        knowledge=SimpleNamespace(embedding_model=embedding_model, embedding_provider="azure_ai"),
    )


# --------------------------------------------------------------------------
# Per-endpoint matrix
# --------------------------------------------------------------------------


async def _run_endpoint_matrix(
    matrix: Matrix,
    label: str,
    api_base: str,
    settings: dict[str, str],
    *,
    base_number: int,
) -> None:
    """Save check, chat, streaming, tools, embeddings and a bad deployment."""
    from enhancements.providers.azure import foundry
    from services.llm_gateway import chat_completions, embeddings

    api_key = settings["api_key"]
    chat_model = settings["chat_deployment"]
    embedding_model = settings["embedding_deployment"]
    config = _build_config(api_base, api_key, chat_model, embedding_model)

    profile = foundry.endpoint_profile(api_base)
    route = foundry.litellm_route({"api_base": api_base})
    matrix.record(
        base_number,
        f"[{label}] endpoint classified and routed",
        BLOCKER,
        "pass",
        f"profile={profile} route={route}",
    )

    # 1. Save-time validation with valid credentials.
    try:
        await foundry.lightweight_health_check({"api_base": api_base, "api_key": api_key})
        matrix.record(1, f"[{label}] save-time check with valid credentials", BLOCKER, "pass")
    except PermissionError as exc:
        # Listing can need a permission inference does not. Not a failure.
        matrix.record(
            1,
            f"[{label}] save-time check with valid credentials",
            BLOCKER,
            "pass",
            f"listing not permitted for this identity, reported as such: {exc}",
        )
    except Exception as exc:
        matrix.record(
            1,
            f"[{label}] save-time check with valid credentials",
            BLOCKER,
            "fail",
            _describe_exception(exc),
        )

    # 3. Chat.
    try:
        response = await chat_completions(
            {
                "model": f"azure_ai:{chat_model}",
                "messages": [{"role": "user", "content": "Reply with the word OK."}],
                "max_tokens": 16,
            },
            config=config,
        )
        text = response["choices"][0]["message"].get("content") or ""
        matrix.record(3, f"[{label}] chat", BLOCKER, "pass", f"reply={text.strip()[:40]!r}")
    except Exception as exc:
        matrix.record(3, f"[{label}] chat", BLOCKER, "fail", _describe_exception(exc))

    # 4. Streaming.
    try:
        stream = await chat_completions(
            {
                "model": f"azure_ai:{chat_model}",
                "messages": [{"role": "user", "content": "Count: one two three."}],
                "max_tokens": 32,
                "stream": True,
            },
            config=config,
        )
        frames = 0
        async for _frame in stream:
            frames += 1
        status = "pass" if frames > 1 else "fail"
        matrix.record(
            4,
            f"[{label}] streaming",
            BLOCKER,
            status,
            f"{frames} SSE frames" + ("" if frames > 1 else " — expected more than one"),
        )
    except Exception as exc:
        matrix.record(4, f"[{label}] streaming", BLOCKER, "fail", _describe_exception(exc))

    # 5. Tool calling.
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Look up the weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    try:
        response = await chat_completions(
            {
                "model": f"azure_ai:{chat_model}",
                "messages": [{"role": "user", "content": "What is the weather in Lisbon?"}],
                "tools": tools,
                "max_tokens": 128,
            },
            config=config,
        )
        message = response["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if calls:
            matrix.record(
                5,
                f"[{label}] tool calling",
                BLOCKER,
                "pass",
                f"called {calls[0]['function']['name']}",
            )
        else:
            # The deployment answering in prose is a model behaviour, not a
            # routing fault — but tools are a product claim, so it blocks.
            matrix.record(
                5,
                f"[{label}] tool calling",
                BLOCKER,
                "fail",
                "no tool_calls returned; the deployment may not support tools",
            )
    except Exception as exc:
        matrix.record(5, f"[{label}] tool calling", BLOCKER, "fail", _describe_exception(exc))

    # 6. Embeddings.
    try:
        response = await embeddings(
            {"model": f"azure_ai:{embedding_model}", "input": ["live validation probe"]},
            config=config,
        )
        vector = response["data"][0]["embedding"]
        matrix.record(6, f"[{label}] embeddings", BLOCKER, "pass", f"{len(vector)} dimensions")
    except Exception as exc:
        matrix.record(6, f"[{label}] embeddings", BLOCKER, "fail", _describe_exception(exc))

    # 7. A deployment that does not exist must fail cleanly, not hang or 200.
    try:
        await chat_completions(
            {
                "model": "azure_ai:openrag-live-validation-no-such-deployment",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 8,
            },
            config=config,
        )
        matrix.record(
            7,
            f"[{label}] unknown deployment is rejected",
            BLOCKER,
            "fail",
            "the call succeeded against a deployment that should not exist",
        )
    except Exception as exc:
        matrix.record(
            7,
            f"[{label}] unknown deployment is rejected",
            BLOCKER,
            "pass",
            _describe_exception(exc)[:160],
        )


# --------------------------------------------------------------------------
# Standalone checks
# --------------------------------------------------------------------------


async def _check_invalid_key(matrix: Matrix, api_base: str) -> None:
    from enhancements.providers.azure import foundry

    try:
        await foundry.lightweight_health_check(
            {"api_base": api_base, "api_key": "openrag-live-validation-invalid-key"}
        )
        matrix.record(
            2,
            "invalid API key is rejected at save time",
            BLOCKER,
            "fail",
            "an invalid key passed the save-time check",
        )
    except PermissionError as exc:
        matrix.record(
            2,
            "invalid API key is rejected at save time",
            BLOCKER,
            "fail",
            f"reported as a permissions problem rather than a bad credential: {exc}",
        )
    except Exception as exc:
        matrix.record(
            2,
            "invalid API key is rejected at save time",
            BLOCKER,
            "pass",
            _describe_exception(exc)[:160],
        )


#: A 1x1 PNG. Enough for a picture-description request to be well-formed.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def _check_docling_vlm(matrix: Matrix, api_base: str, settings: dict[str, str]) -> None:
    """Build the block OpenRAG hands docling-serve, then issue that request.

    docling-serve is not involved: the point is that the URL, headers and
    params OpenRAG produces are accepted by Foundry as given.
    """
    import httpx

    from services.docling_service import DoclingService

    deployment = settings.get("vlm_deployment")
    if not deployment:
        matrix.record(
            10,
            "Docling VLM picture description",
            BLOCKER,
            "skipped",
            "set AZURE_AI_VLM_DEPLOYMENT to run this — it is a blocker for the flip",
        )
        return

    knowledge = SimpleNamespace(
        ocr=False,
        ocr_languages=[],
        table_structure=False,
        picture_descriptions=True,
        vlm_enabled=True,
        vlm_provider="azure_ai",
        vlm_model=f"azure_ai:{deployment}",
        vlm_prompt="Describe this image in one short sentence.",
        vlm_max_tokens=64,
        vlm_watsonx_api_version="2024-01-01",
    )
    config = SimpleNamespace(
        knowledge=knowledge,
        providers=SimpleNamespace(
            credential_values=lambda _key, **_kw: {
                "api_base": api_base,
                "api_key": settings["api_key"],
            }
        ),
    )

    import services.docling_service as docling_module

    original = docling_module.get_openrag_config
    docling_module.get_openrag_config = lambda: config
    try:
        options = await DoclingService()._build_docling_options_async()
    except Exception as exc:
        matrix.record(
            10,
            "Docling VLM picture description",
            BLOCKER,
            "fail",
            f"could not build the request: {_describe_exception(exc)}",
        )
        return
    finally:
        docling_module.get_openrag_config = original

    api = options.get("picture_description_api")
    if not api:
        matrix.record(
            10, "Docling VLM picture description", BLOCKER, "fail", "no request was built"
        )
        return

    # The model name must have shed its provider tag before it goes upstream.
    if api["params"].get("model") != deployment:
        matrix.record(
            10,
            "Docling VLM picture description",
            BLOCKER,
            "fail",
            f"model sent as {api['params'].get('model')!r}, expected {deployment!r}",
        )
        return

    image = base64.b64encode(_PIXEL_PNG).decode()
    payload = {
        **api["params"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": api["prompt"]},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image}"},
                    },
                ],
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(api["url"], headers=api["headers"], json=payload)
        if response.status_code == 200:
            matrix.record(
                10,
                "Docling VLM picture description",
                BLOCKER,
                "pass",
                "Foundry accepted the request OpenRAG builds for docling-serve",
            )
        else:
            matrix.record(
                10,
                "Docling VLM picture description",
                BLOCKER,
                "fail",
                f"HTTP {response.status_code}: {response.text[:200]}",
            )
    except Exception as exc:
        matrix.record(
            10, "Docling VLM picture description", BLOCKER, "fail", _describe_exception(exc)
        )


async def _check_legacy_header_behaviour(
    matrix: Matrix, legacy_base: str | None, api_key: str
) -> None:
    """The question open since the routing design: does `/models` take Bearer?

    `foundry.health_headers` sends both styles because litellm itself is
    inconsistent — its `azure_ai` chat path sends `api-key` while its embedding
    path sends `Bearer` to the same endpoint. This measures what the endpoint
    actually accepts, one header at a time.

    Advisory: the shipped code sends both, so it works either way. The answer
    decides whether that belt-and-braces can be simplified later.
    """
    import httpx

    if not legacy_base:
        matrix.record(
            12,
            "legacy /models header behaviour",
            ADVISORY,
            "skipped",
            "set AZURE_AI_LEGACY_API_BASE to measure this",
        )
        return

    from enhancements.providers.azure import foundry

    url = foundry.models_url(legacy_base)
    results = []
    for style, headers in (
        ("api-key", {"api-key": api_key}),
        ("Bearer", {"Authorization": f"Bearer {api_key}"}),
    ):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
            results.append(f"{style}={response.status_code}")
        except Exception as exc:
            results.append(f"{style}=error({type(exc).__name__})")
    matrix.record(12, "legacy /models header behaviour", ADVISORY, "pass", ", ".join(results))


def _check_secret_leak(matrix: Matrix, api_key: str) -> None:
    """Nothing this run produced may contain the key."""
    haystack = "\n".join(text for text in matrix.captured_text if text)
    if api_key and api_key in haystack:
        matrix.record(
            11,
            "no credential in errors or logs",
            BLOCKER,
            "fail",
            "the API key appeared in captured error or log output",
        )
        return
    matrix.record(
        11,
        "no credential in errors or logs",
        BLOCKER,
        "pass",
        f"scanned {len(haystack)} characters of error and log output",
    )


def _check_cost_attribution(matrix: Matrix, api_base: str, chat_model: str) -> None:
    """Advisory by agreement: OpenRAG does not consume cost data today."""
    from enhancements.providers.azure import foundry

    route = foundry.litellm_route({"api_base": api_base})
    if route == foundry.LITELLM_PROVIDER:
        matrix.record(
            13,
            "cost attribution",
            ADVISORY,
            "pass",
            "native route keeps litellm's azure_ai price rows",
        )
        return
    try:
        import litellm

        mapped = f"azure_ai/{chat_model}" in litellm.model_cost
    except Exception:
        mapped = False
    matrix.record(
        13,
        "cost attribution",
        ADVISORY,
        "pass",
        (
            f"transport route {route!r} has no price row; "
            + (
                f"base_model='azure_ai/{chat_model}' would restore it"
                if mapped
                else "the deployment name is not in any price table either"
            )
            + " — not consumed by OpenRAG today"
        ),
    )


# --------------------------------------------------------------------------
# Log capture
# --------------------------------------------------------------------------


class _Recorder:
    """Collects every structlog call so check 11 can scan it."""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def __getattr__(self, _name):
        def _log(message="", **fields):
            self._sink.append(f"{message} {fields}")

        return _log


def _install_recorders(sink: list[str]) -> None:
    from enhancements.providers.azure import foundry
    from services import docling_service, llm_gateway

    for module in (foundry, llm_gateway, docling_service):
        module.logger = _Recorder(sink)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _settings() -> dict[str, str]:
    required = {
        "api_base": "AZURE_AI_API_BASE",
        "api_key": "AZURE_AI_API_KEY",
        "chat_deployment": "AZURE_AI_CHAT_DEPLOYMENT",
        "embedding_deployment": "AZURE_AI_EMBEDDING_DEPLOYMENT",
    }
    optional = {
        "project_api_base": "AZURE_AI_PROJECT_API_BASE",
        "legacy_api_base": "AZURE_AI_LEGACY_API_BASE",
        "vlm_deployment": "AZURE_AI_VLM_DEPLOYMENT",
    }
    values = {
        name: os.environ.get(env, "").strip() for name, env in {**required, **optional}.items()
    }
    missing = [env for name, env in required.items() if not values[name]]
    if missing:
        print("Missing required environment variables:", ", ".join(missing), file=sys.stderr)
        print(__doc__ or "", file=sys.stderr)
        raise SystemExit(2)
    return values


async def _main() -> int:
    settings = _settings()
    matrix = Matrix()
    _install_recorders(matrix.captured_text)

    endpoints: list[tuple[str, str, int]] = [("resource v1", settings["api_base"], 8)]
    if settings.get("project_api_base"):
        endpoints.append(("project v1", settings["project_api_base"], 9))
    if settings.get("legacy_api_base"):
        endpoints.append(("legacy /models", settings["legacy_api_base"], 14))

    for label, api_base, number in endpoints:
        print(f"\n--- {label}: {api_base} ---", flush=True)
        await _run_endpoint_matrix(matrix, label, api_base, settings, base_number=number)

    if not settings.get("project_api_base"):
        matrix.record(
            9,
            "project /openai/v1",
            ADVISORY,
            "skipped",
            "set AZURE_AI_PROJECT_API_BASE if this resource has a project endpoint",
        )

    await _check_invalid_key(matrix, settings["api_base"])
    await _check_docling_vlm(matrix, settings["api_base"], settings)
    await _check_legacy_header_behaviour(
        matrix, settings.get("legacy_api_base"), settings["api_key"]
    )
    _check_cost_attribution(matrix, settings["api_base"], settings["chat_deployment"])
    # Last: it scans everything the run produced.
    _check_secret_leak(matrix, settings["api_key"])

    print("\n" + "=" * 78)
    print("Azure AI Foundry live validation")
    print("=" * 78)
    symbols = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}
    for check in sorted(matrix.checks, key=lambda c: (c.number, c.name)):
        tag = "blocker " if check.severity == BLOCKER else "advisory"
        print(f"  [{symbols[check.status]}] ({tag}) {check.number:>2}. {check.name}")
        if check.detail:
            print(f"         {check.detail}")

    blocking_failures = [c for c in matrix.checks if c.severity == BLOCKER and c.status == "fail"]
    blocking_skips = [c for c in matrix.checks if c.severity == BLOCKER and c.status == "skipped"]
    print("-" * 78)
    if blocking_failures:
        print(f"{len(blocking_failures)} blocker(s) failed. Do not enable the provider.")
        return 1
    if blocking_skips:
        print(
            f"{len(blocking_skips)} blocker(s) were not exercised. "
            "The matrix is incomplete; do not enable the provider yet."
        )
        return 1
    print("All blockers passed. The visibility flip can proceed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception:  # pragma: no cover - operator-facing script
        traceback.print_exc()
        raise SystemExit(1) from None
