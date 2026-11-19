"""Snapshot-import fixture scripts: endpoint derivation and dataset integrity."""

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "scripts" / "snapshot_fixture"
sys.path.insert(0, str(FIXTURE))

import backup_to_s3  # noqa: E402
import create_index  # noqa: E402


def _args(endpoint: str, cluster_endpoint: str | None = None) -> Namespace:
    return Namespace(endpoint=endpoint, cluster_endpoint=cluster_endpoint)


@pytest.mark.parametrize(
    ("endpoint", "cluster_endpoint", "expected"),
    [
        # The fixture cluster reaches the local MinIO over the compose network.
        ("http://localhost:9100", None, ("minio:9000", "http")),
        ("http://127.0.0.1:9100", None, ("minio:9000", "http")),
        # Any other store is reached at the same host the caller gave.
        ("https://s3.us-east-1.amazonaws.com", None, ("s3.us-east-1.amazonaws.com", "https")),
        ("http://storage.internal:9000", None, ("storage.internal:9000", "http")),
        # An explicit cluster endpoint wins, keeping the caller's protocol.
        ("https://s3.example.com", "s3-internal:443", ("s3-internal:443", "https")),
    ],
)
def test_cluster_endpoint_derivation(endpoint, cluster_endpoint, expected):
    assert backup_to_s3.cluster_endpoint(_args(endpoint, cluster_endpoint)) == expected


def test_backup_defaults_target_local_minio(monkeypatch):
    for name in ("SNAPSHOT_S3_ENDPOINT", "SNAPSHOT_S3_BUCKET", "SNAPSHOT_NAME"):
        monkeypatch.delenv(name, raising=False)
    args = backup_to_s3.parse_args([])
    assert args.endpoint == "http://localhost:9100"
    assert (args.bucket, args.base_path, args.snapshot) == (
        "openrag-snapshots",
        "scientists",
        "scientists-v1",
    )
    assert args.indices.split(",") == ["famous_scientists", "scientific_discoveries"]


def test_backup_credentials_are_overridable(monkeypatch):
    monkeypatch.setenv("SNAPSHOT_S3_ACCESS_KEY", "AKIAEXAMPLE")
    monkeypatch.setenv("SNAPSHOT_S3_SECRET_KEY", "example-secret")
    args = backup_to_s3.parse_args(["--bucket", "customer-bucket"])
    assert (args.access_key, args.secret_key, args.bucket) == (
        "AKIAEXAMPLE",
        "example-secret",
        "customer-bucket",
    )


@pytest.mark.parametrize("name", sorted(create_index.INDICES))
def test_fixture_documents_fit_their_mapping(name):
    body, path = create_index.INDICES[name]
    mapped = set(body["mappings"]["properties"])
    docs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert docs, f"{path.name} is empty"
    ids = [doc["id"] for doc in docs]
    assert len(ids) == len(set(ids)), "document ids must be unique"
    for doc in docs:
        assert set(doc) - {"id"} <= mapped, f"{doc['id']} has unmapped fields"


def test_discoveries_analyser_reads_a_file_outside_the_snapshot():
    settings = create_index.DISCOVERIES_BODY["settings"]["analysis"]
    synonyms_path = settings["filter"]["field_synonyms"]["synonyms_path"]
    assert (FIXTURE / synonyms_path).is_file()
    rules = [
        line
        for line in (FIXTURE / synonyms_path).read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert "dna, deoxyribonucleic acid" in rules
    # The probe in create_index.py depends on Photo 51 mentioning DNA, not the synonym.
    photo = next(
        json.loads(line)
        for line in (FIXTURE / "data" / "scientific_discoveries.jsonl").read_text().splitlines()
        if '"photo-51"' in line
    )
    assert "DNA" in photo["description"] and "deoxyribonucleic" not in photo["description"].lower()
