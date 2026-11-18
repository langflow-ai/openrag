"""Search configuration and scoring constants.

All tuneable values live in ``search_scoring.json`` next to this file.
Edit that file; this module just loads and re-exports the values so the
rest of the backend can import them as before.
"""

import json
from pathlib import Path

_scoring = json.loads((Path(__file__).parent / "search_scoring.json").read_text())

HYBRID_PIPELINE_NAME: str = _scoring["hybrid_pipeline_name"]

DEFAULT_SEARCH_SCORE_THRESHOLD: float = _scoring["score_threshold"]

SEMANTIC_WEIGHT: float = _scoring["semantic_weight"]
KEYWORD_WEIGHT: float = _scoring["keyword_weight"]
