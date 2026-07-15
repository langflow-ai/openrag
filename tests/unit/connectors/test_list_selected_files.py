"""BaseConnector.list_selected_files() — owns the cfg save/restore so
callers don't have to manually back up and restore file_ids/folder_ids."""

from dataclasses import dataclass

import pytest

from connectors.base import BaseConnector


@dataclass
class _FakeCfg:
    file_ids: list[str] | None = None
    folder_ids: list[str] | None = None


class _FakeConnector(BaseConnector):
    CONNECTOR_TYPE = "fake"

    def __init__(self):
        self.cfg = _FakeCfg(file_ids=["orig-1"], folder_ids=["folder-orig"])

    async def authenticate(self):
        return True

    async def setup_subscription(self):
        return ""

    async def list_files(self, page_token=None, max_files=None, **kwargs):
        return {"files": [{"id": fid} for fid in (self.cfg.file_ids or [])]}

    async def get_file_content(self, file_id):
        raise NotImplementedError

    async def handle_webhook(self, payload):
        return []

    async def cleanup_subscription(self, subscription_id):
        return True


@pytest.mark.asyncio
async def test_restores_cfg_after_success():
    conn = _FakeConnector()
    result = await conn.list_selected_files(["a", "b"])
    assert [f["id"] for f in result["files"]] == ["a", "b"]
    assert conn.cfg.file_ids == ["orig-1"]
    assert conn.cfg.folder_ids == ["folder-orig"]


@pytest.mark.asyncio
async def test_restores_cfg_after_exception():
    class _Broken(_FakeConnector):
        async def list_files(self, **kwargs):
            raise RuntimeError("boom")

    conn = _Broken()
    with pytest.raises(RuntimeError, match="boom"):
        await conn.list_selected_files(["x"])
    assert conn.cfg.file_ids == ["orig-1"]
    assert conn.cfg.folder_ids == ["folder-orig"]


@pytest.mark.asyncio
async def test_folder_ids_cleared_by_default():
    """list_selected_files sets folder_ids to None during the call."""
    observed_folder_ids = None

    class _Capture(_FakeConnector):
        async def list_files(self, **kwargs):
            nonlocal observed_folder_ids
            observed_folder_ids = self.cfg.folder_ids
            return {"files": []}

    conn = _Capture()
    await conn.list_selected_files(["a"])
    assert observed_folder_ids is None


@pytest.mark.asyncio
async def test_folder_ids_passed_through():
    observed = {}

    class _Capture(_FakeConnector):
        async def list_files(self, **kwargs):
            nonlocal observed
            observed = {"file_ids": self.cfg.file_ids, "folder_ids": self.cfg.folder_ids}
            return {"files": []}

    conn = _Capture()
    await conn.list_selected_files(["f1"], folder_ids=["fold-1"])
    assert observed == {"file_ids": ["f1"], "folder_ids": ["fold-1"]}
    assert conn.cfg.file_ids == ["orig-1"]
    assert conn.cfg.folder_ids == ["folder-orig"]
