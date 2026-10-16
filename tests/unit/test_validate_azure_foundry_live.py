"""The live-validation harness's own safety properties.

`scripts/validate_azure_foundry_live.py` is run by hand against a real Foundry
resource, so its failure modes are not otherwise exercised by CI. Two of them
are worth pinning: it must never put a real credential on a terminal, and the
checks that pass by observing a rejection must not pass on an unrelated one.

The leak tests matter because detection alone is not enough. Check 11 finds a
leak *after* the run, by which point anything written to stdout or stderr is
already on screen and, in CI, already in a retained build log.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "validate_azure_foundry_live.py"

REAL_KEY = "primary-credential-must-never-be-printed"
LISTING_DENIED_KEY = "listing-denied-credential-also-secret"


@pytest.fixture
def harness():
    """The script as an importable module, with its secret list reset."""
    spec = importlib.util.spec_from_file_location("azure_foundry_live_validation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        module._set_real_secrets()
        sys.modules.pop(spec.name, None)


class TestRedaction:
    def test_every_supplied_credential_is_redacted(self, harness) -> None:
        harness._set_real_secrets(REAL_KEY, LISTING_DENIED_KEY)
        text = f"key={REAL_KEY} other={LISTING_DENIED_KEY}"

        cleaned = harness._redact(text)

        assert REAL_KEY not in cleaned
        assert LISTING_DENIED_KEY not in cleaned
        assert cleaned.count("<redacted>") == 2

    def test_a_short_value_is_not_treated_as_a_secret(self, harness) -> None:
        """Blanking a two-character value would destroy the output instead."""
        harness._set_real_secrets("ab")
        assert harness._redact("a table of absolute values") == "a table of absolute values"

    def test_blank_credentials_are_ignored(self, harness) -> None:
        harness._set_real_secrets("", None or "")
        assert harness._REAL_SECRETS == ()


class TestTeeDoesNotLeakToTheTerminal:
    """The stream forwards redacted text and keeps the original for detection."""

    @pytest.mark.parametrize("secret", [REAL_KEY, LISTING_DENIED_KEY])
    def test_the_real_stream_never_receives_the_secret(self, harness, secret) -> None:
        harness._set_real_secrets(REAL_KEY, LISTING_DENIED_KEY)
        terminal = io.StringIO()
        sink: list[str] = []
        tee = harness._Tee(terminal, sink)

        tee.write(f"litellm debug: authorization=Bearer {secret}\n")

        assert secret not in terminal.getvalue()
        assert "<redacted>" in terminal.getvalue()
        # ...but the capture keeps the original, or check 11 could not detect it.
        assert any(secret in fragment for fragment in sink)


class TestCheckElevenDetectsEitherCredential:
    @pytest.mark.parametrize(
        "leaked, index",
        [(REAL_KEY, 1), (LISTING_DENIED_KEY, 2)],
    )
    def test_a_forced_leak_of_either_credential_fails_the_check(
        self, harness, leaked, index
    ) -> None:
        matrix = harness.Matrix()
        matrix.capture(f"some library wrote {leaked} to stderr")

        harness._check_secret_leak(matrix, (REAL_KEY, LISTING_DENIED_KEY))

        check = matrix.checks[-1]
        assert check.status == "fail"
        assert check.severity == harness.BLOCKER
        assert f"credential #{index}" in check.detail

    def test_the_failure_detail_never_contains_the_secret(self, harness) -> None:
        """Reporting a leak must not be the leak."""
        matrix = harness.Matrix()
        matrix.capture(f"leaked {REAL_KEY} here")

        harness._check_secret_leak(matrix, (REAL_KEY,))

        assert REAL_KEY not in matrix.checks[-1].detail

    def test_a_clean_run_passes_and_says_how_much_it_scanned(self, harness) -> None:
        matrix = harness.Matrix()
        matrix.capture("nothing sensitive at all")

        harness._check_secret_leak(matrix, (REAL_KEY, LISTING_DENIED_KEY))

        check = matrix.checks[-1]
        assert check.status == "pass"
        assert "2 credential(s)" in check.detail

    def test_no_credentials_to_scan_is_a_failure_not_a_pass(self, harness) -> None:
        """An empty secret list would otherwise pass vacuously."""
        matrix = harness.Matrix()

        harness._check_secret_leak(matrix, ())

        assert matrix.checks[-1].status == "fail"


class TestTheReportCannotPrintASecret:
    @pytest.mark.parametrize("secret", [REAL_KEY, LISTING_DENIED_KEY])
    def test_a_secret_echoed_into_a_check_detail_is_redacted_on_print(
        self, harness, secret, capsys
    ) -> None:
        """A provider can echo the credential back in an error body.

        That body ends up in a check's detail, so the report has to redact on
        the way out even though check 11 has already flagged it.
        """
        harness._set_real_secrets(REAL_KEY, LISTING_DENIED_KEY)
        matrix = harness.Matrix()
        matrix.record(
            2,
            "invalid API key is rejected at save time",
            harness.BLOCKER,
            "fail",
            f'upstream echoed the credential: body={{"key": "{secret}"}}',
        )

        harness._print_report(matrix)

        assert secret not in capsys.readouterr().out


class TestNotFoundClassification:
    """A bare 404 is not evidence: those digits appear in ids and counters."""

    @pytest.mark.parametrize(
        "text",
        [
            "DeploymentNotFound",
            "The API deployment for this resource does not exist",
            "model_not_found",
            "HTTP 404",
            "HTTP/1.1 404",
            "status_code: 404",
            "status=404",
            "404 Not Found",
        ],
    )
    def test_a_real_not_found_is_recognised(self, harness, text) -> None:
        assert harness._looks_like_not_found(text)

    @pytest.mark.parametrize(
        "text",
        [
            "request id 8a404b2c",
            "used 404 prompt tokens",
            "completed in 404ms",
            "x-ms-request-id: 404aa1",
            "rate limit exceeded",
        ],
    )
    def test_an_incidental_404_is_not_mistaken_for_one(self, harness, text) -> None:
        assert not harness._looks_like_not_found(text)


class TestFailureCategories:
    """Checks that pass on a rejection must not pass on an unrelated failure."""

    @pytest.mark.parametrize(
        "text",
        [
            "ConnectError: nodename nor servname provided, or not known",
            "Cannot connect to host contoso.services.ai.azure.com:443",
            "ReadTimeout",
            "certificate verify failed",
        ],
    )
    def test_transport_failures_are_identified_as_such(self, harness, text) -> None:
        assert harness._looks_like_connectivity_failure(text)
        assert not harness._looks_like_credential_failure(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Access denied due to invalid subscription key",
            "401 Unauthorized",
            "Incorrect API key provided",
            "HTTP 401",
            "status_code: 401",
        ],
    )
    def test_credential_rejections_are_identified_as_such(self, harness, text) -> None:
        assert harness._looks_like_credential_failure(text)
        assert not harness._looks_like_connectivity_failure(text)

    @pytest.mark.parametrize(
        "text",
        [
            "request id 8a401b2c",
            "completed in 401 ms",
            "prompt_tokens: 401",
        ],
    )
    def test_an_incidental_401_is_not_mistaken_for_a_rejection(self, harness, text) -> None:
        """Same reasoning as the 404 case above.

        Check 2 runs this classifier over 300 characters of response body, so
        a request id carrying those three digits would otherwise let a
        non-credential rejection pass as a credential one.
        """
        assert not harness._looks_like_credential_failure(text)


class TestTheRoutingCheckCanFail:
    """A blocker that always passes is not a check.

    Both paths below return before any network call, which is what makes them
    testable without a live resource.
    """

    @pytest.fixture
    def settings(self):
        return {
            "api_key": REAL_KEY,
            "chat_deployment": "chat-dep",
            "embedding_deployment": "embed-dep",
        }

    @pytest.mark.asyncio
    async def test_the_wrong_surface_is_reported_rather_than_passed(
        self, harness, settings, monkeypatch
    ) -> None:
        """A legacy `/models` URL in AZURE_AI_API_BASE used to satisfy the
        `/openai/v1` blocker, which is the one thing the matrix exists to
        prove."""
        from enhancements.providers.azure import foundry

        monkeypatch.setattr(foundry, "endpoint_profile", lambda _b: "legacy_models")
        monkeypatch.setattr(foundry, "litellm_route", lambda _s: "azure_ai")

        matrix = harness.Matrix()
        await harness._run_endpoint_matrix(
            matrix,
            "resource v1",
            "https://contoso.services.ai.azure.com/models",
            settings,
            base_number=8,
            expected_profile="resource_openai_v1",
        )

        assert [c.status for c in matrix.checks] == ["fail"]
        assert "expected resource_openai_v1" in matrix.checks[0].detail

    @pytest.mark.asyncio
    async def test_an_unclassifiable_endpoint_does_not_abort_the_run(
        self, harness, settings, monkeypatch
    ) -> None:
        """`litellm_route` refuses what it cannot classify, by design.

        Uncaught, that exception escaped `_run_all_checks` and the report was
        never printed — a traceback instead of the matrix, which is the least
        useful thing a release gate can hand an operator.
        """
        from enhancements.providers.azure import foundry

        def _refuse(_stored):
            raise foundry.UnsupportedEndpointError(foundry.UNSUPPORTED_ENDPOINT_MESSAGE)

        monkeypatch.setattr(foundry, "endpoint_profile", lambda _b: "unknown")
        monkeypatch.setattr(foundry, "litellm_route", _refuse)

        matrix = harness.Matrix()
        await harness._run_endpoint_matrix(
            matrix,
            "resource v1",
            "https://contoso.services.ai.azure.com/anthropic/v1",
            settings,
            base_number=8,
            expected_profile="resource_openai_v1",
        )

        assert [c.status for c in matrix.checks] == ["fail"]
        assert "UnsupportedEndpointError" in matrix.checks[0].detail


class TestBlockersRejectUnusableSuccesses:
    """A 200 is not the same as a working deployment.

    Both of these recorded a pass on a successful-but-empty response, which
    made the release matrix green without usable inference — the one outcome
    a blocker here has to rule out.
    """

    @pytest.mark.parametrize("text", ["", "   ", "\n"])
    def test_an_empty_completion_is_not_a_pass(self, harness, text) -> None:
        assert harness._unusable_chat_reply(text)

    def test_a_real_completion_passes(self, harness) -> None:
        assert harness._unusable_chat_reply("OK") == ""

    @pytest.mark.parametrize(
        "vector",
        [
            [],
            None,
            "not-a-vector",
            [0.1, float("nan")],
            [float("inf"), 0.2],
            [0.1, "0.2"],
            [0.1, True],
        ],
    )
    def test_an_unusable_vector_is_not_a_pass(self, harness, vector) -> None:
        """Length alone is not enough: a vector of NaN has the right shape and
        is useless for retrieval, and OpenSearch rejects it at index time
        rather than here."""
        assert harness._unusable_embedding(vector)

    def test_a_real_vector_passes(self, harness) -> None:
        assert harness._unusable_embedding([0.1, -0.2, 3]) == ""


class TestTheEndpointIsNeverPrintedRaw:
    """`_redact` only knows the credentials this run was handed.

    A secret carried *inside* the endpoint is invisible to it, and the
    provider module strips or refuses one only after this line is on screen.
    """

    def test_userinfo_and_query_are_removed(self, harness) -> None:
        shown = harness._safe_endpoint(
            "https://operator:s3cr3t@contoso.services.ai.azure.com/openai/v1?sig=abc123"
        )
        assert "s3cr3t" not in shown
        assert "operator" not in shown
        assert "abc123" not in shown
        assert "sig" not in shown
        assert shown.startswith("https://contoso.services.ai.azure.com/openai/v1")
        assert "userinfo" in shown and "query" in shown

    def test_an_ordinary_endpoint_is_left_alone(self, harness) -> None:
        plain = "https://contoso.services.ai.azure.com/openai/v1"
        assert harness._safe_endpoint(plain) == plain

    def test_a_non_url_is_passed_through(self, harness) -> None:
        assert harness._safe_endpoint("not-a-url") == "not-a-url"


class TestPreboundLogHandlersCannotLeak:
    """Replacing `sys.stderr` does not retarget a handler that already holds it.

    litellm attaches three such handlers at import, and it is the library most
    likely to log a request detail carrying a credential — so without this the
    harness's central promise, that nothing reaches a terminal unredacted,
    does not hold for the most likely source.
    """

    def test_a_handler_bound_before_the_block_is_redirected(self, harness, monkeypatch) -> None:
        import logging

        # The handler must hold the *same object* `sys.stderr` names when
        # `_capturing` is entered — that is the situation litellm creates at
        # import, and the one swapping `sys.stderr` fails to cover. A handler
        # pointed somewhere else entirely is a log file, not a terminal, and
        # is deliberately left alone.
        terminal = io.StringIO()
        monkeypatch.setattr(sys, "stderr", terminal)
        logger = logging.getLogger("test.prebound.handler")
        logger.propagate = False
        handler = logging.StreamHandler(terminal)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        harness._set_real_secrets(REAL_KEY)
        sink: list[str] = []
        try:
            with harness._capturing(sink):
                logger.info("leaking %s now", REAL_KEY)
        finally:
            logger.removeHandler(handler)

        assert REAL_KEY not in terminal.getvalue(), "the secret reached the real stream"
        assert handler.stream is terminal, "the handler's stream was not restored"
        assert any(REAL_KEY in entry for entry in sink), "detection still needs the original"


class TestImageFixture:
    def test_the_probe_image_is_large_enough_to_be_accepted(self, harness) -> None:
        """A 1x1 PNG is valid but some vision deployments reject it on size,
        which would read as an integration failure rather than a fixture one."""
        import struct

        png = harness._sample_png()

        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", png[16:24])
        assert width == height == 128
