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
        ],
    )
    def test_credential_rejections_are_identified_as_such(self, harness, text) -> None:
        assert harness._looks_like_credential_failure(text)
        assert not harness._looks_like_connectivity_failure(text)


class TestImageFixture:
    def test_the_probe_image_is_large_enough_to_be_accepted(self, harness) -> None:
        """A 1x1 PNG is valid but some vision deployments reject it on size,
        which would read as an integration failure rather than a fixture one."""
        import struct

        png = harness._sample_png()

        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", png[16:24])
        assert width == height == 128
