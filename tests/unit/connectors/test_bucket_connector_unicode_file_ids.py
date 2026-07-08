"""Regression coverage: bucket-style connectors (IBM COS, Azure Blob) must
preserve non-ASCII (e.g. Japanese) object keys unchanged through their
composite file-id round trip.

`document.id` (built from `_make_file_id`) is what downstream ingestion now
passes as `connector_file_id` — it must stay the raw, unmangled key so the
bucket/key can still be split back out for delete/status lookups
(`enhancements/connectors/*/api.py`), even though `document_id` itself is now
derived from a hash of this value (see
`tests/unit/test_resolve_document_id_connector_file_id.py`).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from enhancements.connectors.azure_blob.connector import (  # noqa: E402
    _make_file_id as azure_make_file_id,
)
from enhancements.connectors.azure_blob.connector import (  # noqa: E402
    _split_file_id as azure_split_file_id,
)
from enhancements.connectors.ibm_cos.connector import (  # noqa: E402
    _make_file_id as cos_make_file_id,
)
from enhancements.connectors.ibm_cos.connector import (  # noqa: E402
    _split_file_id as cos_split_file_id,
)

JAPANESE_KEY = "報告書.pdf"
JAPANESE_NESTED_KEY = "フォルダ/報告書_最終版.pdf"


def test_cos_file_id_round_trips_japanese_key():
    file_id = cos_make_file_id("my-bucket", JAPANESE_KEY)

    assert file_id == f"my-bucket::{JAPANESE_KEY}"
    bucket, key = cos_split_file_id(file_id)
    assert bucket == "my-bucket"
    assert key == JAPANESE_KEY


def test_cos_file_id_round_trips_nested_japanese_key():
    file_id = cos_make_file_id("my-bucket", JAPANESE_NESTED_KEY)

    bucket, key = cos_split_file_id(file_id)
    assert bucket == "my-bucket"
    assert key == JAPANESE_NESTED_KEY


def test_azure_file_id_round_trips_japanese_blob_name():
    file_id = azure_make_file_id("my-container", JAPANESE_KEY)

    assert file_id == f"my-container::{JAPANESE_KEY}"
    container, blob = azure_split_file_id(file_id)
    assert container == "my-container"
    assert blob == JAPANESE_KEY
