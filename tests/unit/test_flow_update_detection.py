"""Flow-update detection must key on content, not on file timestamps.

``_check_flow_update`` compared the flow file's mtime against Langflow's
``updated_at``. mtime says nothing about content: git checkout / pull / stash,
a branch switch, a fresh clone, and any container rebuild that re-COPYs
``flows/`` restamp every flow file without changing a byte. That made the
"Update required from Langflow" prompt reappear more or less permanently.
"""

import json

import pytest

from services.flows_service import FlowsService


def _flow(*, code_hash: str = "abc123", extra_node: bool = False, value: str = "1000") -> dict:
    nodes = [
        {
            "id": "SplitText-1",
            "position": {"x": 0, "y": 0},
            "data": {
                "id": "SplitText-1",
                "type": "SplitText",
                "node": {
                    "metadata": {"code_hash": code_hash},
                    "template": {"chunk_size": {"value": value}},
                },
            },
        }
    ]
    if extra_node:
        nodes.append(
            {
                "id": "Operations-2",
                "position": {"x": 10, "y": 10},
                "data": {
                    "id": "Operations-2",
                    "type": "Operations",
                    "node": {"metadata": {"code_hash": "def456"}, "template": {}},
                },
            }
        )
    return {
        "id": "flow-1",
        "data": {
            "nodes": nodes,
            "edges": [
                {
                    "source": "SplitText-1",
                    "target": "Operations-2",
                    "sourceHandle": "out",
                    "targetHandle": "in",
                }
            ],
        },
    }


def test_signature_ignores_positions_and_template_values():
    """OpenRAG rewrites values in Langflow every time settings are applied.

    Chunk size, models and credentials all get patched into the Langflow copy,
    so a signature covering them would differ forever and report a permanent
    update.
    """
    disk = _flow(value="1000")
    in_langflow = _flow(value="500")
    in_langflow["data"]["nodes"][0]["position"] = {"x": 999, "y": 999}

    assert FlowsService._flow_structure_signature(
        disk
    ) == FlowsService._flow_structure_signature(in_langflow)


def test_signature_changes_when_component_code_changes():
    assert FlowsService._flow_structure_signature(
        _flow(code_hash="abc123")
    ) != FlowsService._flow_structure_signature(_flow(code_hash="zzz999"))


def test_signature_changes_when_a_component_is_added():
    assert FlowsService._flow_structure_signature(
        _flow()
    ) != FlowsService._flow_structure_signature(_flow(extra_node=True))


def test_signature_is_none_for_unusable_payloads():
    assert FlowsService._flow_structure_signature(None) is None
    assert FlowsService._flow_structure_signature({}) is None
    assert FlowsService._flow_structure_signature({"data": {"nodes": "nope"}}) is None


@pytest.mark.asyncio
async def test_restamped_but_unchanged_flow_reports_no_update(tmp_path, monkeypatch):
    """A newer mtime with identical content must not raise the prompt."""
    service = FlowsService()
    flow_path = tmp_path / "ingestion_flow.json"
    flow_path.write_text(json.dumps(_flow()), encoding="utf-8")

    monkeypatch.setattr(service, "_find_flow_file_by_id", lambda flow_id: str(flow_path))

    langflow_copy = _flow(value="500")  # value drift from applying settings
    langflow_copy["updated_at"] = "2000-01-01T00:00:00Z"  # far older than the file
    langflow_copy["locked"] = True

    assert await service._check_flow_update("ingest", "flow-1", langflow_copy) is None


@pytest.mark.asyncio
async def test_genuinely_changed_flow_still_reports_an_update(tmp_path, monkeypatch):
    service = FlowsService()
    flow_path = tmp_path / "ingestion_flow.json"
    flow_path.write_text(json.dumps(_flow(code_hash="new-code")), encoding="utf-8")

    monkeypatch.setattr(service, "_find_flow_file_by_id", lambda flow_id: str(flow_path))

    langflow_copy = _flow(code_hash="old-code")
    langflow_copy["updated_at"] = "2000-01-01T00:00:00Z"
    langflow_copy["locked"] = True

    update = await service._check_flow_update("ingest", "flow-1", langflow_copy)

    assert update == {"flow_type": "ingest", "flow_id": "flow-1", "is_custom": False}


@pytest.mark.asyncio
async def test_older_file_short_circuits_before_reading_it(tmp_path, monkeypatch):
    """The mtime check stays as the cheap pre-filter."""
    service = FlowsService()
    flow_path = tmp_path / "ingestion_flow.json"
    flow_path.write_text(json.dumps(_flow(code_hash="new-code")), encoding="utf-8")

    monkeypatch.setattr(service, "_find_flow_file_by_id", lambda flow_id: str(flow_path))

    def explode(*_args, **_kwargs):
        raise AssertionError("should not read the flow file when Langflow's copy is newer")

    monkeypatch.setattr(service, "_disk_flow_payload", explode)

    langflow_copy = _flow(code_hash="old-code")
    langflow_copy["updated_at"] = "2999-01-01T00:00:00Z"
    langflow_copy["locked"] = True

    assert await service._check_flow_update("ingest", "flow-1", langflow_copy) is None
