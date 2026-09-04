"""The default agent prompt's contract with the URL ingestion tool."""

from config.config_manager import DEFAULT_SYSTEM_PROMPT
from config.legacy_prompts import LEGACY_SYSTEM_PROMPTS


def test_url_tool_guidance_demands_a_bare_url():
    """The fetcher takes its whole input as one address.

    Langflow's URL component runs `ensure_url` on the tool's input verbatim: it
    prepends `https://` to anything without a scheme and rejects the result if
    it is not a URL. So an agent that passed the user's phrasing through —
    "Please ingest this URL: https://example.com" — failed ingestion outright,
    which is exactly what gpt-4.1 did until the prompt said otherwise.
    """
    assert "bare URL" in DEFAULT_SYSTEM_PROMPT


def test_the_shipped_default_is_not_also_listed_as_legacy():
    """Startup only rewrites a stored prompt that is legacy or the default.

    Listing the current default as legacy too would make that check meaningless
    — every install would look upgradable forever.
    """
    assert DEFAULT_SYSTEM_PROMPT not in LEGACY_SYSTEM_PROMPTS


def test_the_previous_default_stays_in_the_legacy_list():
    """Existing installs store the old default verbatim in config.yaml.

    They only pick up a new default if the old one is recognised as legacy, so
    dropping a superseded prompt from this list strands those deployments on it.
    """
    superseded = [
        prompt
        for prompt in LEGACY_SYSTEM_PROMPTS
        if "You are the OpenRAG Agent." in prompt and "bare URL" not in prompt
    ]
    assert superseded, "the prompt replaced by the current default must remain listed"


def test_no_evidence_rule_spares_general_knowledge():
    """An empty retrieval must not turn into a refusal for any question.

    The rule used to say "no supporting evidence" → emit the canned sentence,
    full stop. gpt-4.1 followed that literally and answered "What is the
    capital of France?" with "No relevant supporting sources were found for
    that request" — the knowledge base was never meant to cover France.
    """
    assert "general knowledge the documents were never expected to cover" in DEFAULT_SYSTEM_PROMPT


def test_no_evidence_rule_keeps_the_exact_refusal_sentence():
    """Three E2E tests match on this wording when the documents really are the subject."""
    assert '"No relevant supporting sources were found for that request."' in DEFAULT_SYSTEM_PROMPT
