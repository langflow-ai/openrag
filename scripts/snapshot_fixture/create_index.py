#!/usr/bin/env python3
"""Create the snapshot-import fixture indices on the source OpenSearch.

Two indices with deliberately different shapes, so an import has to map
fields per index:

* ``famous_scientists``: 30 people (text, keyword, date, keyword arrays).
* ``scientific_discoveries``: 21 discoveries; its search analyser reads a
  synonym file through ``synonyms_path``. That file is not part of a snapshot,
  which is the case the import preflight must handle.

Usage:
    uv run python scripts/snapshot_fixture/create_index.py [--url http://localhost:9201]
"""

from __future__ import annotations

import argparse
import json
import sys

from common import DATA_DIR, OpenSearch, OpenSearchError, read_jsonl

SCIENTISTS_INDEX = "famous_scientists"
DISCOVERIES_INDEX = "scientific_discoveries"

SCIENTISTS_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "born": {"type": "date"},
            "died": {"type": "date"},
            "nationality": {"type": "keyword"},
            "field": {"type": "keyword"},
            "known_for": {"type": "text"},
            "awards": {"type": "keyword"},
            "biography": {"type": "text", "analyzer": "english"},
            "wikipedia_url": {"type": "keyword"},
        }
    },
}

DISCOVERIES_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "filter": {
                "field_synonyms": {
                    "type": "synonym_graph",
                    "synonyms_path": "analysis/field_synonyms.txt",
                }
            },
            "analyzer": {
                "discovery_search": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "field_synonyms"],
                }
            },
        },
    },
    "mappings": {
        "properties": {
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "year": {"type": "integer"},
            "scientist": {"type": "keyword"},
            "field": {"type": "keyword"},
            "description": {
                "type": "text",
                "analyzer": "standard",
                "search_analyzer": "discovery_search",
            },
        }
    },
}

INDICES = {
    SCIENTISTS_INDEX: (SCIENTISTS_BODY, DATA_DIR / "famous_scientists.jsonl"),
    DISCOVERIES_INDEX: (DISCOVERIES_BODY, DATA_DIR / "scientific_discoveries.jsonl"),
}


def create_index(
    client: OpenSearch, name: str, body: dict, docs: list[dict], recreate: bool
) -> int:
    exists = True
    try:
        client.request("HEAD", f"/{name}")
    except OpenSearchError as exc:
        if exc.status != 404:
            raise
        exists = False
    if exists and recreate:
        client.request("DELETE", f"/{name}")
        exists = False
    if not exists:
        client.request("PUT", f"/{name}", body)

    lines = []
    for doc in docs:
        source = {k: v for k, v in doc.items() if k != "id"}
        lines.append(json.dumps({"index": {"_index": name, "_id": doc["id"]}}))
        lines.append(json.dumps(source))
    result = client.request("POST", "/_bulk?refresh=true", "\n".join(lines) + "\n", ndjson=True)
    if result.get("errors"):
        failed = [item for item in result["items"] if item["index"].get("error")]
        raise RuntimeError(f"Bulk load into {name} failed for {len(failed)} docs: {failed[:2]}")
    return client.request("GET", f"/{name}/_count")["count"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--url", default="http://localhost:9201", help="Source OpenSearch URL")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the indices")
    args = parser.parse_args(argv)

    client = OpenSearch(args.url, args.username, args.password, verify_tls=not args.insecure)
    client.wait_until_ready()
    for name, (body, path) in INDICES.items():
        count = create_index(client, name, body, read_jsonl(path), args.recreate)
        print(f"{name}: {count} documents")

    # Prove the synonym analyser is live on the source: "deoxyribonucleic acid"
    # only matches the Photo 51 record through the synonym file.
    probe = client.request(
        "POST",
        f"/{DISCOVERIES_INDEX}/_search",
        {"query": {"match": {"description": "deoxyribonucleic acid"}}, "_source": ["title"]},
    )
    titles = [hit["_source"]["title"] for hit in probe["hits"]["hits"]]
    print(f"synonym probe 'deoxyribonucleic acid' -> {titles}")
    if "Photo 51" not in titles:
        print("ERROR: synonym analyser is not active on the source index", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
