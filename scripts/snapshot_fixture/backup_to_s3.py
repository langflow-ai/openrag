#!/usr/bin/env python3
"""Back up the fixture indices from the source OpenSearch into S3-like storage.

Defaults target the local MinIO started by ``make snapshot-fixture-up``. Point
it at any S3-compatible store by passing its endpoint and credentials (flags or
the SNAPSHOT_S3_* environment variables)::

    uv run python scripts/snapshot_fixture/backup_to_s3.py \\
        --endpoint https://s3.us-east-1.amazonaws.com --region us-east-1 \\
        --access-key AKIA... --secret-key ... --bucket my-bucket --base-path scientists

What it does:
  1. Creates the bucket if missing (``--no-create-bucket`` to skip).
  2. Points the source cluster's ``s3.client.<client>`` at the endpoint. The
     endpoint is a static node setting, so the fixture container is recreated
     when it changes; keys go into the node keystore and are reloaded.
  3. Registers an ``s3`` snapshot repository and takes a snapshot of the indices.
  4. Verifies the snapshot and lists what landed in the bucket.

``--container ''`` skips step 2 for a cluster this script does not run; that
cluster must already have the S3 client configured.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from urllib.parse import urlparse

from common import COMPOSE_FILE, SOURCE_CONTAINER, OpenSearch, OpenSearchError

DEFAULT_INDICES = "famous_scientists,scientific_discoveries"
LOCAL_MINIO_PORT = os.getenv("SNAPSHOT_MINIO_PORT", "9100")


def env(name: str, default: str) -> str:
    return os.getenv(name) or default


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument(
        "--url",
        default=env("SNAPSHOT_SOURCE_OS_URL", "http://localhost:9201"),
        help="Source OpenSearch URL",
    )
    p.add_argument(
        "--endpoint",
        default=env("SNAPSHOT_S3_ENDPOINT", f"http://localhost:{LOCAL_MINIO_PORT}"),
        help="S3 endpoint URL as reachable from this machine (and from OpenRAG)",
    )
    p.add_argument(
        "--cluster-endpoint",
        default=os.getenv("SNAPSHOT_S3_CLUSTER_ENDPOINT"),
        help="host:port the source cluster uses; derived from --endpoint when omitted",
    )
    p.add_argument("--region", default=env("SNAPSHOT_S3_REGION", "us-east-1"))
    p.add_argument("--access-key", default=env("SNAPSHOT_S3_ACCESS_KEY", "snapshotadmin"))
    p.add_argument("--secret-key", default=env("SNAPSHOT_S3_SECRET_KEY", "snapshotadmin123"))
    p.add_argument("--bucket", default=env("SNAPSHOT_S3_BUCKET", "openrag-snapshots"))
    p.add_argument("--base-path", default=env("SNAPSHOT_S3_BASE_PATH", "scientists"))
    p.add_argument("--repository", default=env("SNAPSHOT_REPOSITORY", "fixture_s3"))
    p.add_argument("--snapshot", default=env("SNAPSHOT_NAME", "scientists-v1"))
    p.add_argument("--indices", default=env("SNAPSHOT_INDICES", DEFAULT_INDICES))
    p.add_argument("--client", default="default", help="s3.client.<name> to configure and use")
    p.add_argument(
        "--container",
        default=env("SNAPSHOT_SOURCE_CONTAINER", SOURCE_CONTAINER),
        help="Docker container of the source cluster; '' to skip keystore setup",
    )
    p.add_argument("--no-create-bucket", action="store_true")
    p.add_argument(
        "--overwrite", action="store_true", help="Replace an existing snapshot of that name"
    )
    return p.parse_args(argv)


def cluster_endpoint(args: argparse.Namespace) -> tuple[str, str]:
    """Return (host:port, protocol) the source cluster should use for S3."""
    parsed = urlparse(args.endpoint)
    protocol = parsed.scheme or "https"
    if args.cluster_endpoint:
        return args.cluster_endpoint, protocol
    host, port = parsed.hostname or "", parsed.port
    # The fixture cluster reaches the local MinIO over the compose network.
    if host in ("localhost", "127.0.0.1") and str(port) == LOCAL_MINIO_PORT:
        return "minio:9000", "http"
    return (f"{host}:{port}" if port else host), protocol


def ensure_bucket(args: argparse.Namespace) -> None:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=args.endpoint,
        region_name=args.region,
        aws_access_key_id=args.access_key,
        aws_secret_access_key=args.secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )
    try:
        s3.head_bucket(Bucket=args.bucket)
        print(f"bucket {args.bucket}: exists")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
            raise
        kwargs = {"Bucket": args.bucket}
        if args.region and args.region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": args.region}
        s3.create_bucket(**kwargs)
        print(f"bucket {args.bucket}: created")


def bucket_summary(args: argparse.Namespace) -> tuple[int, int]:
    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        endpoint_url=args.endpoint,
        region_name=args.region,
        aws_access_key_id=args.access_key,
        aws_secret_access_key=args.secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )
    count = size = 0
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=args.bucket, Prefix=args.base_path.rstrip("/") + "/"
    ):
        for obj in page.get("Contents", []):
            count += 1
            size += obj["Size"]
    return count, size


def container_env(container: str) -> dict[str, str]:
    out = subprocess.run(
        ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def configure_source_cluster(args: argparse.Namespace, client: OpenSearch) -> None:
    endpoint, protocol = cluster_endpoint(args)
    prefix = f"s3.client.{args.client}"
    current = container_env(args.container)
    wanted = {
        f"{prefix}.endpoint": endpoint,
        f"{prefix}.protocol": protocol,
        f"{prefix}.region": args.region,
    }
    if args.client != "default":
        raise SystemExit(
            "--client other than 'default' needs --container '' and a pre-configured cluster"
        )
    if any(current.get(k) != v for k, v in wanted.items()):
        print(f"recreating {args.container} with S3 endpoint {protocol}://{endpoint}")
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "up",
                "-d",
                "--no-deps",
                "source-opensearch",
            ],
            check=True,
            env={
                **os.environ,
                "SNAPSHOT_S3_CLUSTER_ENDPOINT": endpoint,
                "SNAPSHOT_S3_CLUSTER_PROTOCOL": protocol,
                "SNAPSHOT_S3_REGION": args.region,
            },
        )
        client.wait_until_ready()

    script = (
        "set -e; cd /usr/share/opensearch; "
        "bin/opensearch-keystore list >/dev/null 2>&1 || bin/opensearch-keystore create >/dev/null; "
        f'printf %s "$S3_ACCESS_KEY" | bin/opensearch-keystore add --stdin --force {prefix}.access_key; '
        f'printf %s "$S3_SECRET_KEY" | bin/opensearch-keystore add --stdin --force {prefix}.secret_key'
    )
    subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"S3_ACCESS_KEY={args.access_key}",
            "-e",
            f"S3_SECRET_KEY={args.secret_key}",
            args.container,
            "bash",
            "-c",
            script,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    reload = client.request("POST", "/_nodes/reload_secure_settings", {})
    failed = reload.get("_nodes", {}).get("failed", 0)
    if failed:
        raise RuntimeError(f"reload_secure_settings failed on {failed} node(s): {reload}")
    print(f"source cluster: {prefix} -> {protocol}://{endpoint} (keys reloaded)")


def take_snapshot(args: argparse.Namespace, client: OpenSearch) -> dict:
    client.request(
        "PUT",
        f"/_snapshot/{args.repository}",
        {
            "type": "s3",
            "settings": {"bucket": args.bucket, "base_path": args.base_path, "client": args.client},
        },
    )
    try:
        client.request("GET", f"/_snapshot/{args.repository}/{args.snapshot}")
        if not args.overwrite:
            raise SystemExit(
                f"snapshot {args.snapshot} already exists; pass --overwrite or a new --snapshot"
            )
        client.request("DELETE", f"/_snapshot/{args.repository}/{args.snapshot}")
    except OpenSearchError as exc:
        if exc.status != 404:
            raise
    result = client.request(
        "PUT",
        f"/_snapshot/{args.repository}/{args.snapshot}?wait_for_completion=true",
        {"indices": args.indices, "include_global_state": False},
    )
    snap = result["snapshot"]
    if snap["state"] != "SUCCESS":
        raise RuntimeError(f"snapshot finished in state {snap['state']}: {snap}")
    return snap


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = OpenSearch(args.url)
    client.wait_until_ready()
    if not args.no_create_bucket:
        ensure_bucket(args)
    if args.container:
        configure_source_cluster(args, client)
    snap = take_snapshot(args, client)
    count, size = bucket_summary(args)
    summary = {
        "snapshot": snap["snapshot"],
        "uuid": snap["uuid"],
        "version": snap["version"],
        "indices": sorted(snap["indices"]),
        "shards": snap["shards"],
        "s3": {
            "endpoint": args.endpoint,
            "region": args.region,
            "bucket": args.bucket,
            "base_path": args.base_path,
            "objects": count,
            "bytes": size,
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
