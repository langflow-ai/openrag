"""Shared fakes for the engine tests: in-memory S3 and a recording OpenSearch client."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from botocore.exceptions import ClientError

FIXTURES = Path(__file__).parent / "fixtures"
REPO_DIR = FIXTURES / "scientists_repo"
BUCKET = "bucket"
PREFIX = "scientists"
SNAP_V1 = "scientists-v1"
SNAP_V1_UUID = "Ap8kzmvfRjmWFLieWVuxjQ"
SCIENTISTS_ID = "vQoty04XTbCKBAxXf9HqKQ"
DISCOVERIES_ID = "PPA1PiDSRBKgmt_dh6Pgaw"


def load_repo(root: Path = REPO_DIR) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "Op",
    )


class _Body:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, amt: int | None = None) -> bytes:
        return self._buf.read(amt) if amt is not None else self._buf.read()

    def close(self) -> None:
        pass


class FakeS3:
    """Subset of the boto3 S3 client over an in-memory object map (keys include the prefix)."""

    def __init__(
        self, files: dict[str, bytes] | None = None, *, prefix: str = PREFIX, bucket: str = BUCKET
    ):
        self.bucket = bucket
        self.objects: dict[str, bytes] = {
            f"{prefix}/{k}" if prefix else k: v for k, v in (files or {}).items()
        }
        self.calls: list[tuple[str, dict]] = []
        self.on_get: Any = None  # optional hook(key) -> bytes | None
        self.uploads: dict[str, dict] = {}
        self.put_kwargs: dict[str, dict] = {}
        self.multipart_kwargs: dict[str, dict] = {}

    def _check(self, bucket: str) -> None:
        if bucket != self.bucket:
            raise client_error("NoSuchBucket", 404)

    def list_objects_v2(self, **kw: Any) -> dict:
        self.calls.append(("list", kw))
        self._check(kw["Bucket"])
        prefix = kw.get("Prefix", "")
        delimiter = kw.get("Delimiter")
        keys = sorted(k for k in self.objects if k.startswith(prefix))
        if delimiter:
            keys = [k for k in keys if delimiter not in k[len(prefix) :]]
        limit = kw.get("MaxKeys", 1000)
        start = int(kw.get("ContinuationToken", 0))
        page = keys[start : start + limit]
        truncated = start + limit < len(keys)
        resp: dict[str, Any] = {
            "Contents": [{"Key": k, "Size": len(self.objects[k])} for k in page],
            "IsTruncated": truncated,
        }
        if truncated:
            resp["NextContinuationToken"] = str(start + limit)
        return resp

    def head_object(self, **kw: Any) -> dict:
        self.calls.append(("head", kw))
        self._check(kw["Bucket"])
        if kw["Key"] not in self.objects:
            raise client_error("404", 404)
        return {"ContentLength": len(self.objects[kw["Key"]])}

    def get_object(self, **kw: Any) -> dict:
        self.calls.append(("get", kw))
        self._check(kw["Bucket"])
        key = kw["Key"]
        data = self.objects.get(key)
        if self.on_get is not None:
            data = self.on_get(key, data)
        if data is None:
            raise client_error("NoSuchKey", 404)
        return {"Body": _Body(data), "ContentLength": len(data)}

    def get_keys(self) -> list[str]:
        return [kw["Key"] for name, kw in self.calls if name == "get"]

    # -- write side (staging destination)
    def put_object(self, **kw: Any) -> dict:
        self.calls.append(("put", {k: v for k, v in kw.items() if k != "Body"}))
        self.objects[kw["Key"]] = bytes(kw["Body"])
        self.put_kwargs[kw["Key"]] = {k: v for k, v in kw.items() if k != "Body"}
        return {}

    def create_multipart_upload(self, **kw: Any) -> dict:
        self.calls.append(("create_multipart", kw))
        upload_id = f"u{len(self.uploads)}"
        self.uploads[upload_id] = {"key": kw["Key"], "parts": {}}
        self.multipart_kwargs[kw["Key"]] = dict(kw)
        return {"UploadId": upload_id}

    def upload_part(self, **kw: Any) -> dict:
        self.calls.append(("upload_part", {k: v for k, v in kw.items() if k != "Body"}))
        self.uploads[kw["UploadId"]]["parts"][kw["PartNumber"]] = bytes(kw["Body"])
        return {"ETag": f"e{kw['PartNumber']}"}

    def complete_multipart_upload(self, **kw: Any) -> dict:
        self.calls.append(("complete", {k: v for k, v in kw.items()}))
        upload = self.uploads.pop(kw["UploadId"])
        order = [p["PartNumber"] for p in kw["MultipartUpload"]["Parts"]]
        self.objects[upload["key"]] = b"".join(upload["parts"][n] for n in order)
        return {}

    def abort_multipart_upload(self, **kw: Any) -> dict:
        self.calls.append(("abort", kw))
        self.uploads.pop(kw["UploadId"], None)
        return {}

    def delete_objects(self, **kw: Any) -> dict:
        self.calls.append(("delete_objects", kw))
        for item in kw["Delete"]["Objects"]:
            self.objects.pop(item["Key"], None)
        return {}


class StubSource:
    """Minimal source for staging tests: serves bytes and a movable repository generation."""

    def __init__(self, files: dict[str, bytes], generation: int = 1):
        self.files = dict(files)
        self.generation = generation
        self.streamed: list[str] = []
        self.hook: Any = None

    async def repository_generation(self) -> int:
        return self.generation

    async def stream(self, key: str, expected_size: int):
        self.streamed.append(key)
        data = self.files[key]
        if self.hook is not None:
            data = self.hook(key, data) or data
        for i in range(0, len(data), 1000):
            yield data[i : i + 1000]


class ApiError(Exception):
    def __init__(self, status: int, reason: str = "boom"):
        super().__init__(reason)
        self.status_code = status
        self.info = {"error": {"reason": reason, "type": "x"}}


class FakeOpenSearch:
    """Records calls; behaviour is configured through plain attributes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.version_number = "3.8.0"
        self.repo_error: Exception | None = None
        self.health_sequence: list[dict] = [{"status": "green"}]
        self.health_error: Exception | None = None
        self.explain: dict = {}
        self.restore_error: Exception | None = None
        self.count_value = 7
        self.nodes: dict = {}
        self.cluster_settings: dict = {"defaults": {}, "persistent": {}, "transient": {}}
        self.stats_error: Exception | None = None
        self.cat_rows: list[dict] = []
        self.cat_nodes_rows: list[
            dict
        ] = []  # e.g. [{"node.role": "dimr"}]; empty: node count unknown
        self.cat_nodes_error: Exception | None = None
        self.mapping: dict = {}
        self.hits: list[dict] = []
        self.transport = SimpleNamespace(perform_request=self._perform)
        self.perform_error: Exception | None = None
        self.perform_result: Any = {}
        self.snapshot = SimpleNamespace(
            get_repository=self._get_repository,
            restore=self._restore,
            create_repository=self._create_repository,
            delete_repository=self._delete_repository,
        )
        self.cluster = SimpleNamespace(
            health=self._health, allocation_explain=self._explain, get_settings=self._get_settings
        )
        self.indices = SimpleNamespace(
            update_aliases=self._update_aliases, delete=self._delete, get_mapping=self._get_mapping
        )
        self.nodes_ns = SimpleNamespace(stats=self._stats)
        self.nodes_api = self.nodes_ns
        self.cat = SimpleNamespace(indices=self._cat_indices, nodes=self._cat_nodes)

    # opensearchpy exposes ``client.nodes.stats``
    @property
    def nodes(self) -> Any:  # type: ignore[override]
        return self.nodes_ns

    @nodes.setter
    def nodes(self, value: dict) -> None:
        self._nodes_doc = value

    def _rec(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))

    async def info(self) -> dict:
        self._rec("info")
        return {"version": {"number": self.version_number, "distribution": "opensearch"}}

    async def _get_repository(self, **kw: Any) -> dict:
        self._rec("get_repository", **kw)
        if self.repo_error:
            raise self.repo_error
        return {}

    async def _restore(self, **kw: Any) -> dict:
        self._rec("restore", **kw)
        if self.restore_error:
            raise self.restore_error
        return {"accepted": True}

    async def _health(self, **kw: Any) -> dict:
        self._rec("health", **kw)
        if self.health_error:
            raise self.health_error
        if len(self.health_sequence) > 1:
            return self.health_sequence.pop(0)
        return self.health_sequence[0]

    async def _explain(self, **kw: Any) -> dict:
        self._rec("allocation_explain", **kw)
        return self.explain

    async def _get_settings(self, **kw: Any) -> dict:
        self._rec("get_settings", **kw)
        return self.cluster_settings

    async def _stats(self, **kw: Any) -> dict:
        self._rec("nodes_stats", **kw)
        if self.stats_error:
            raise self.stats_error
        return {"nodes": getattr(self, "_nodes_doc", {})}

    async def count(self, **kw: Any) -> dict:
        self._rec("count", **kw)
        return {"count": self.count_value}

    async def search(self, **kw: Any) -> dict:
        self._rec("search", **kw)
        return {"hits": {"hits": self.hits}}

    async def _update_aliases(self, **kw: Any) -> dict:
        self._rec("update_aliases", **kw)
        return {}

    async def _delete(self, **kw: Any) -> dict:
        self._rec("indices_delete", **kw)
        return {}

    async def _get_mapping(self, **kw: Any) -> dict:
        self._rec("get_mapping", **kw)
        return self.mapping

    async def _cat_indices(self, **kw: Any) -> list[dict]:
        self._rec("cat_indices", **kw)
        return self.cat_rows

    async def _cat_nodes(self, **kw: Any) -> list[dict]:
        self._rec("cat_nodes", **kw)
        if self.cat_nodes_error:
            raise self.cat_nodes_error
        return self.cat_nodes_rows

    async def _create_repository(self, **kw: Any) -> dict:
        self._rec("create_repository", **kw)
        return {}

    async def _delete_repository(self, **kw: Any) -> dict:
        self._rec("delete_repository", **kw)
        if self.repo_error:
            raise self.repo_error
        return {}

    async def _perform(self, method: str, path: str, **kw: Any) -> Any:
        self._rec("perform_request", method=method, path=path, **kw)
        if self.perform_error:
            raise self.perform_error
        return self.perform_result
