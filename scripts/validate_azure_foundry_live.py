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
    # A credential that can run inference but NOT list deployments, if one can
    # be created. See "The 403 question" below — this is the scenario that
    # decides it.
    export AZURE_AI_LISTING_DENIED_API_KEY="<key with inference but not listing>"

    uv run python scripts/validate_azure_foundry_live.py

Exit code is non-zero if any **blocker** fails. Blockers are the capabilities
the product claims once the provider is visible: supported endpoint routing,
chat, streaming, tool calling, embeddings, Docling VLM, and error
sanitization. Cost attribution is reported but never blocks — OpenRAG does not
consume cost data today (see the transport trade-off in `foundry.py`).

The 403 question
----------------
`foundry.lightweight_health_check` raises `PermissionError` for a 403 on the
deployment listing, on the reasoning that listing can need a permission
inference does not. **But the product does not act on that distinction.**
`api/settings/endpoints.py` catches `Exception` around provider validation and
returns HTTP 400, so a `PermissionError` is indistinguishable from a bad key:
the provider cannot be saved either way.

So a 403 on a valid credential is *not* treated as a pass here. This script
gathers the evidence needed to decide between two fixes — require listing
permission and say so, or make a specifically-identified listing denial
non-blocking in the settings endpoint — by recording exactly what Foundry
returns for:

  * a valid key with normal permissions;
  * a deliberately invalid key;
  * a valid credential that can infer but not list, when one is available
    (`AZURE_AI_LISTING_DENIED_API_KEY`).

Until that evidence exists, a generic 403 is reported as **inconclusive and
blocking**. Do not relax it on the strength of a status code alone: the
distinction is only safe if the responses are reliably distinguishable.

Secrets
-------
The API key is never printed. The run captures root logging, stdout, stderr
and every recorded exception, and check 11 scans all of it. When a secret is
found the captured material is **not** printed — only the fact and where.

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
import contextlib
import logging
import os
import struct
import sys
import traceback
import zlib
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


#: A failure that says nothing about credentials or deployments — the request
#: did not get a considered answer. Any check that "passes on an error" has to
#: exclude these, or an unplugged network reads as a successful rejection.
_CONNECTIVITY_MARKERS = (
    "nodename nor servname",
    "name or service not known",
    "temporary failure in name resolution",
    "cannot connect to host",
    "connection refused",
    "connection reset",
    "connect call failed",
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "timeout",
    "timed out",
    "certificate",
    "ssl",
    "tlsv1",
    "proxyerror",
)

#: Upstream said the deployment or model is not there. Azure words this
#: differently across its two surfaces, so both vocabularies are covered.
_NOT_FOUND_MARKERS = (
    "deploymentnotfound",
    "deployment not found",
    "does not exist",
    "model_not_found",
    "model not found",
    "unknown model",
    "no deployment",
    "resourcenotfound",
    "404",
)


def _looks_like_connectivity_failure(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _CONNECTIVITY_MARKERS)


def _looks_like_not_found(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _NOT_FOUND_MARKERS)


def _looks_like_credential_failure(text: str) -> bool:
    """Upstream rejected the credential, per OpenRAG's own classifier."""
    from api.provider_validation import is_provider_credential_error

    lowered = (text or "").lower()
    if is_provider_credential_error(lowered):
        return True
    # Azure's own vocabulary for a rejected key, which the shared marker list
    # does not have to know about.
    return any(
        marker in lowered
        for marker in (
            "401",
            "unauthorized",
            "access denied due to invalid subscription key",
            "invalid subscription key",
            "permissiondenied",
            "invalid authentication",
            "accessdenied",
        )
    )


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

    # 1. Save-time validation with valid credentials. Delegated to the
    # credential-semantics probe so the raw response is on record, not just
    # whether an exception was raised.
    await _probe_credential(
        matrix,
        number=1,
        name=f"[{label}] save-time check with valid credentials",
        api_base=api_base,
        api_key=api_key,
        scenario="valid",
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

    # 7. A deployment that does not exist must fail as a *not found*, through
    # the gateway's own error contract. Passing on any exception would let a
    # DNS failure or a 500 stand in for the rejection this proves.
    from services.llm_gateway import LlmGatewayError

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
    except LlmGatewayError as exc:
        # `detail` is the internal text; `message` is what a caller is shown.
        # Upstream 404s are deliberately mapped to 502 by the gateway, so the
        # status is not the discriminator — the cause is.
        detail = f"{exc.detail}"
        if _looks_like_connectivity_failure(detail):
            matrix.record(
                7,
                f"[{label}] unknown deployment is rejected",
                BLOCKER,
                "fail",
                f"could not reach the endpoint, so nothing was proved: {detail[:160]}",
            )
        elif _looks_like_not_found(detail):
            matrix.record(
                7,
                f"[{label}] unknown deployment is rejected",
                BLOCKER,
                "pass",
                f"HTTP {exc.status_code} via the gateway; sanitized message={exc.message[:90]!r}",
            )
        else:
            matrix.record(
                7,
                f"[{label}] unknown deployment is rejected",
                BLOCKER,
                "fail",
                "rejected, but not as a missing deployment — the error does not "
                f"identify the cause: {detail[:160]}",
            )
    except Exception as exc:
        matrix.record(
            7,
            f"[{label}] unknown deployment is rejected",
            BLOCKER,
            "fail",
            "the failure did not come through the gateway's error contract: "
            + _describe_exception(exc)[:160],
        )


# --------------------------------------------------------------------------
# Standalone checks
# --------------------------------------------------------------------------


async def _listing_response(api_base: str, api_key: str) -> tuple[int | None, str]:
    """Raw status and body of the deployment listing, for the record.

    The health check collapses the response into an exception type; deciding
    the 403 question needs the response itself.
    """
    import httpx

    from enhancements.providers.azure import foundry

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                foundry.models_url(api_base), headers=foundry.health_headers({"api_key": api_key})
            )
        return response.status_code, (response.text or "")[:300]
    except Exception as exc:
        return None, _describe_exception(exc)


async def _probe_credential(
    matrix: Matrix,
    *,
    number: int,
    name: str,
    api_base: str,
    api_key: str,
    scenario: str,
) -> None:
    """One credential scenario, recorded as evidence rather than a verdict.

    `scenario` is "valid", "invalid" or "listing_denied". Each has a different
    expected outcome, and a 403 is never silently treated as success — see
    "The 403 question" in the module docstring.
    """
    from enhancements.providers.azure import foundry

    status, body = await _listing_response(api_base, api_key)

    outcome = "accepted"
    detail = ""
    try:
        await foundry.lightweight_health_check({"api_base": api_base, "api_key": api_key})
    except PermissionError as exc:
        outcome, detail = "PermissionError", str(exc)
    except Exception as exc:
        outcome, detail = type(exc).__name__, str(exc)

    # What the product would do: settings/endpoints.py wraps provider
    # validation in `except Exception` and returns 400, so anything raised
    # here — PermissionError included — blocks the save.
    would_save = outcome == "accepted"
    evidence = (
        f"listing HTTP {status if status is not None else 'unreachable'}; "
        f"health check -> {outcome}; provider saveable={would_save}"
    )

    if status is None and _looks_like_connectivity_failure(body):
        matrix.record(number, name, BLOCKER, "fail", f"endpoint unreachable: {body[:140]}")
        return

    if scenario == "valid":
        if would_save:
            matrix.record(number, name, BLOCKER, "pass", evidence)
        elif status == 403:
            matrix.record(
                number,
                name,
                BLOCKER,
                "fail",
                "INCONCLUSIVE, and blocking by design: the credential was accepted "
                "for listing purposes but denied. `lightweight_health_check` raises "
                "PermissionError, and settings/endpoints.py turns that into HTTP 400, "
                "so the provider cannot be saved. Decide whether listing permission "
                "is required or whether this specific denial should be non-blocking, "
                f"using the response below. {evidence}. body={body[:160]!r}",
            )
        else:
            matrix.record(number, name, BLOCKER, "fail", f"{evidence}. body={body[:160]!r}")
        return

    if scenario == "invalid":
        if would_save:
            matrix.record(
                number, name, BLOCKER, "fail", f"an invalid key passed the check. {evidence}"
            )
            return
        combined = f"{detail} {body}"
        if _looks_like_connectivity_failure(combined):
            matrix.record(
                number,
                name,
                BLOCKER,
                "fail",
                f"rejected for a transport reason, which proves nothing: {evidence}",
            )
        elif status is not None and 500 <= status < 600:
            matrix.record(
                number,
                name,
                BLOCKER,
                "fail",
                f"upstream error rather than a credential rejection: {evidence}",
            )
        elif _looks_like_credential_failure(combined) or status == 401:
            matrix.record(number, name, BLOCKER, "pass", evidence)
        else:
            matrix.record(
                number,
                name,
                BLOCKER,
                "fail",
                "rejected, but not identifiably as a bad credential — so a bad key "
                f"is indistinguishable from other failures. {evidence}. "
                f"body={body[:160]!r}",
            )
        return

    # listing_denied: pure evidence gathering, never a pass/fail verdict.
    matrix.record(
        number,
        name,
        ADVISORY,
        "pass",
        "EVIDENCE for the 403 decision — compare with the invalid-key response "
        f"above; they must be reliably distinguishable. {evidence}. "
        f"body={body[:200]!r}",
    )


def _sample_png(size: int = 128) -> bytes:
    """A small PNG with enough structure for a vision model to describe.

    Written here rather than committed as a fixture or a base64 blob so it
    stays readable, and generated at a realistic size: a 1x1 pixel is a valid
    PNG but some vision deployments reject images below a minimum dimension,
    which would show up as an integration failure that is really a fixture
    problem.

    Four coloured quadrants, a dark border, and a white disc in the middle —
    unambiguous enough that a description can be sanity-checked by eye.
    """
    quadrants = ((220, 60, 60), (60, 120, 220), (240, 200, 60), (60, 180, 110))
    centre = size / 2
    radius = size / 5
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            if x < 2 or y < 2 or x >= size - 2 or y >= size - 2:
                pixel = (30, 30, 30)
            elif (x - centre) ** 2 + (y - centre) ** 2 <= radius**2:
                pixel = (250, 250, 250)
            else:
                pixel = quadrants[(1 if x >= centre else 0) + (2 if y >= centre else 0)]
            row.extend(pixel)
        rows.append(bytes(row))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
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

    image = base64.b64encode(_sample_png()).decode()
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
    """Nothing this run produced may contain the key.

    Scans captured root logging, stdout, stderr, OpenRAG's structlog output
    and every recorded exception. On a hit the material is deliberately **not**
    printed — only the fact, how many fragments matched, and the first source
    kind — because printing it is the leak all over again, into a terminal and
    very likely into CI output.
    """
    if not api_key:
        matrix.record(
            11, "no credential in errors or logs", BLOCKER, "fail", "no API key to scan for"
        )
        return

    hits = sum(1 for fragment in matrix.captured_text if fragment and api_key in fragment)
    scanned = sum(len(fragment) for fragment in matrix.captured_text if fragment)
    if hits:
        matrix.record(
            11,
            "no credential in errors or logs",
            BLOCKER,
            "fail",
            f"the API key appeared in {hits} captured fragment(s). The material is "
            "not reproduced here; re-run with a scratch credential and inspect "
            "locally to find the source.",
        )
        return
    matrix.record(
        11,
        "no credential in errors or logs",
        BLOCKER,
        "pass",
        f"scanned {scanned} characters of captured logging, stdout, stderr and errors",
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


class _Tee:
    """A stream that passes writes through and keeps a copy.

    Progress stays visible while everything printed — including anything a
    library writes directly rather than through logging — is available to the
    secret scan.
    """

    def __init__(self, stream, sink: list[str]) -> None:
        self._stream = stream
        self._sink = sink

    def write(self, text: str) -> int:
        self._sink.append(text)
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _SinkHandler(logging.Handler):
    """Root logging handler: catches litellm, httpx and anything else."""

    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink.append(self.format(record))
        except Exception:
            # A handler that raises would be worse than one that misses a
            # line, but a miss weakens the scan — so record that it happened.
            self._sink.append(f"<unformattable log record from {record.name}>")


@contextlib.contextmanager
def _capturing(sink: list[str]):
    """Capture root logging, stdout, stderr and OpenRAG's structlog loggers.

    Everything here feeds check 11. Anything outside it — a library writing to
    a file descriptor directly, or a subprocess — is not covered, which is why
    check 11 reports how much it scanned rather than claiming completeness.
    """
    from enhancements.providers.azure import foundry
    from services import docling_service, llm_gateway

    modules = (foundry, llm_gateway, docling_service)
    original_loggers = [module.logger for module in modules]
    for module in modules:
        module.logger = _Recorder(sink)  # type: ignore[attr-defined]

    root = logging.getLogger()
    handler = _SinkHandler(sink)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout = _Tee(real_stdout, sink)  # type: ignore[assignment]
    sys.stderr = _Tee(real_stderr, sink)  # type: ignore[assignment]
    try:
        yield
    finally:
        sys.stdout, sys.stderr = real_stdout, real_stderr
        root.removeHandler(handler)
        root.setLevel(previous_level)
        for module, logger in zip(modules, original_loggers, strict=True):
            module.logger = logger  # type: ignore[attr-defined]


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
        "listing_denied_api_key": "AZURE_AI_LISTING_DENIED_API_KEY",
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

    endpoints: list[tuple[str, str, int]] = [("resource v1", settings["api_base"], 8)]
    if settings.get("project_api_base"):
        endpoints.append(("project v1", settings["project_api_base"], 9))
    if settings.get("legacy_api_base"):
        endpoints.append(("legacy /models", settings["legacy_api_base"], 14))

    with _capturing(matrix.captured_text):
        await _run_all_checks(matrix, settings, endpoints)

    _print_report(matrix, settings["api_key"], settings.get("listing_denied_api_key", ""))
    return _exit_code(matrix)


async def _run_all_checks(matrix: Matrix, settings: dict[str, str], endpoints) -> None:
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

    await _probe_credential(
        matrix,
        number=2,
        name="invalid API key is rejected at save time",
        api_base=settings["api_base"],
        api_key="openrag-live-validation-invalid-key",
        scenario="invalid",
    )
    if settings.get("listing_denied_api_key"):
        await _probe_credential(
            matrix,
            number=2,
            name="listing-denied credential: what Foundry actually returns",
            api_base=settings["api_base"],
            api_key=settings["listing_denied_api_key"],
            scenario="listing_denied",
        )
    else:
        matrix.record(
            2,
            "listing-denied credential: what Foundry actually returns",
            ADVISORY,
            "skipped",
            "set AZURE_AI_LISTING_DENIED_API_KEY to settle the 403 question; "
            "without it, a 403 on a valid key stays inconclusive and blocking",
        )
    await _check_docling_vlm(matrix, settings["api_base"], settings)
    await _check_legacy_header_behaviour(
        matrix, settings.get("legacy_api_base"), settings["api_key"]
    )
    _check_cost_attribution(matrix, settings["api_base"], settings["chat_deployment"])
    # Last: it scans everything the run produced.
    _check_secret_leak(matrix, settings["api_key"])


def _redact(text: str, *secrets: str) -> str:
    """Remove any known secret from text about to be printed.

    Belt and braces over check 11. That check *detects* a leak; this makes
    sure detecting one does not itself print it, since several checks quote
    an upstream response body and a provider could echo the credential back.
    """
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 8:
            cleaned = cleaned.replace(secret, "<redacted>")
    return cleaned


def _print_report(matrix: Matrix, *secrets: str) -> None:
    print("\n" + "=" * 78)
    print("Azure AI Foundry live validation")
    print("=" * 78)
    symbols = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}
    for check in sorted(matrix.checks, key=lambda c: (c.number, c.name)):
        tag = "blocker " if check.severity == BLOCKER else "advisory"
        print(f"  [{symbols[check.status]}] ({tag}) {check.number:>2}. {check.name}")
        if check.detail:
            print(f"         {_redact(check.detail, *secrets)}")
    print("-" * 78)


def _exit_code(matrix: Matrix) -> int:
    blocking_failures = [c for c in matrix.checks if c.severity == BLOCKER and c.status == "fail"]
    blocking_skips = [c for c in matrix.checks if c.severity == BLOCKER and c.status == "skipped"]
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
