# Snapshot import fixture

A stand-in for a customer's OpenSearch cluster and S3 bucket, for developing
and testing the OpenSearch snapshot import connector. Nothing here is part of
the OpenRAG stack: the fixture cluster plays the "source" OpenSearch that took
the backup, and MinIO plays the customer's S3.

```bash
make snapshot-fixture        # start, load data, back up to local MinIO
make snapshot-fixture-down   # stop and delete all fixture data
```

| Service | URL | Notes |
|---|---|---|
| Source OpenSearch 3.8.0 | http://localhost:9201 | Security disabled; `repository-s3` installed |
| MinIO (S3 API) | http://localhost:9100 | User `snapshotadmin`, password `snapshotadmin123` |
| MinIO console | http://localhost:9101 | Same credentials |

## Dataset

Two indices about famous scientists, with different shapes so an import has to
map fields per index:

| Index | Docs | Shape |
|---|---|---|
| `famous_scientists` | 30 | `name` (text + keyword), `born`/`died` (date), `nationality`, `field`, `awards` (keyword), `known_for`, `biography` (english analyser), `wikipedia_url` |
| `scientific_discoveries` | 21 | `title` (text + keyword), `year`, `scientist`, `field`, `description` with a search analyser that reads `analysis/field_synonyms.txt` through `synonyms_path` |

The synonym file is mounted into the source cluster but is **not** inside the
snapshot, like the synonym indices in the original customer request. Restoring
`scientific_discoveries` elsewhere fails unless the file content is supplied
(the import preflight's `analyser_file_required` case). `create_index.py`
checks the analyser on the source: "deoxyribonucleic acid" must match only
through the synonym file and returns "Photo 51".

Data files: `data/famous_scientists.jsonl`, `data/scientific_discoveries.jsonl`.

## Backing up to another S3-compatible store

`backup_to_s3.py` defaults to the local MinIO. Override any of these (flags or
environment variables; the Makefile passes command-line variables through):

| Variable | Default |
|---|---|
| `SNAPSHOT_S3_ENDPOINT` | `http://localhost:9100` |
| `SNAPSHOT_S3_REGION` | `us-east-1` |
| `SNAPSHOT_S3_ACCESS_KEY` / `SNAPSHOT_S3_SECRET_KEY` | MinIO root credentials |
| `SNAPSHOT_S3_BUCKET` | `openrag-snapshots` (created if missing) |
| `SNAPSHOT_S3_BASE_PATH` | `scientists` |
| `SNAPSHOT_NAME` | `scientists-v1` |
| `SNAPSHOT_OVERWRITE` | unset; `make snapshot-fixture` sets `1` |

```bash
make snapshot-fixture-backup \
  SNAPSHOT_S3_ENDPOINT=https://s3.us-east-1.amazonaws.com \
  SNAPSHOT_S3_ACCESS_KEY=AKIA... SNAPSHOT_S3_SECRET_KEY=... \
  SNAPSHOT_S3_BUCKET=my-bucket SNAPSHOT_NAME=scientists-v2
```

OpenSearch only accepts S3 keys from its keystore, and the S3 endpoint is a
static node setting. The script therefore recreates the fixture container when
the endpoint changes, writes the keys into the keystore and calls
`_nodes/reload_secure_settings`. For a cluster that is not this fixture, pass
`--container ''` and configure its `s3.client.default` yourself.

## Gotchas found while building this

- `minio/minio` images are no longer published on Docker Hub or Quay; the
  fixture uses the community build `pgsty/minio`.
- OpenSearch 3.x `repository-s3` sends an SSE-S3 (`AES256`) header on every
  upload. MinIO rejects it unless a KMS key is configured, so the fixture sets
  a throwaway `MINIO_KMS_SECRET_KEY`.
- Regular snapshots keep every file under `<base_path>/`: `index.latest`,
  `index-<N>` (plain JSON listing snapshots and indices), `snap-*.dat`,
  `meta-*.dat` and `indices/<id>/...`.

## Importing into OpenRAG

Use these values in the OpenSearch snapshot connector: endpoint
`http://localhost:9100` (or `http://host.docker.internal:9100` when the backend
runs in Docker), region `us-east-1`, bucket `openrag-snapshots`, prefix
`scientists`, path-style on, and the MinIO credentials above.
