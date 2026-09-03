"""parse_nudges turns whatever the model returned into clean button labels.

The prompt asks for bare newline-separated strings, but models routinely wrap
them in numbering, bullets, quotes, fences, JSON or a preamble. Anything that
survives here is rendered verbatim as a chat suggestion button, so the parser
is the last line of defence.
"""

import pytest

from services.nudges_service import MAX_NUDGES, parse_nudges


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The happy path the prompt asks for.
        (
            "What is in this corpus?\nSummarize the Q3 report\nList open action items",
            [
                "What is in this corpus?",
                "Summarize the Q3 report",
                "List open action items",
            ],
        ),
        # Numbering, in the three forms models emit.
        ("1. Alpha\n2) Beta\n(3) Gamma", ["Alpha", "Beta", "Gamma"]),
        # Bullets, including unicode.
        ("- Alpha\n* Beta\n• Gamma", ["Alpha", "Beta", "Gamma"]),
        # Quotes, straight and smart, despite "Do not include quotation marks".
        ('"Alpha"\n‘Beta’\n`Gamma`', ["Alpha", "Beta", "Gamma"]),
        # More than three: keep the first three.
        ("A\nB\nC\nD\nE", ["A", "B", "C"]),
        # Blank lines and the template's own separator rules leaking through.
        ("Alpha\n\n----------\nBeta\n   \nGamma", ["Alpha", "Beta", "Gamma"]),
        # Duplicates are explicitly forbidden by the prompt; drop them case-insensitively.
        ("Alpha\nALPHA\nBeta\nGamma", ["Alpha", "Beta", "Gamma"]),
        # A preamble must not consume one of the three slots.
        ("Here are three nudges:\nAlpha\nBeta\nGamma", ["Alpha", "Beta", "Gamma"]),
        # Fenced block.
        ("```\nAlpha\nBeta\nGamma\n```", ["Alpha", "Beta", "Gamma"]),
        ("```json\nAlpha\nBeta\n```", ["Alpha", "Beta"]),
        # JSON array, despite "strings only".
        ('["Alpha", "Beta", "Gamma"]', ["Alpha", "Beta", "Gamma"]),
        # Trailing list punctuation.
        ("Alpha,\nBeta;\nGamma", ["Alpha", "Beta", "Gamma"]),
        # Internal whitespace collapses.
        ("Alpha    with   gaps", ["Alpha with gaps"]),
        # Nothing usable.
        ("", []),
        (None, []),
        ("   ", []),
        ("\n\n", []),
        # "If an error occurs, return a blank string" — the flow's own escape hatch.
        ("-----", []),
    ],
)
def test_parse_nudges(raw, expected):
    assert parse_nudges(raw) == expected


def test_prose_paragraph_is_dropped():
    """A wall of text is the model explaining itself, not a ~40-char nudge."""
    prose = "This corpus appears to contain " + "many documents " * 30
    assert parse_nudges(f"{prose}\nAlpha") == ["Alpha"]


def test_question_marks_and_apostrophes_survive():
    """Trailing-punctuation stripping must not eat real nudge text."""
    assert parse_nudges("What's new?\nSummarize John's notes") == [
        "What's new?",
        "Summarize John's notes",
    ]


def test_never_returns_more_than_max_nudges():
    assert len(parse_nudges("\n".join(f"Nudge {i}" for i in range(20)))) == MAX_NUDGES


def test_round_trips_through_the_frontend_split():
    """The wire format is a newline-joined string that the UI splits again.

    Mirrors `data.response.split("\\n").filter(Boolean)` in useGetNudgesQuery.
    """
    nudges = parse_nudges("1. Alpha\n2. Beta\n3. Gamma")
    wire = "\n".join(nudges)
    assert [line for line in wire.split("\n") if line] == nudges
