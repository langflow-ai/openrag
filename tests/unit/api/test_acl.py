import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class FakeSessionManager:
    def __init__(self, opensearch_client):
        self.opensearch_client = opensearch_client

    def get_user_opensearch_client(self, user_id, jwt_token):
        return self.opensearch_client


class FakeUser:
    user_id = "reader"
    jwt_token = "token"


@pytest.mark.asyncio
async def test_get_document_acl_returns_read_only_acl_for_document():
    from api import acl as acl_module

    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(
        return_value={
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "owner": "owner",
                            "allowed_users": ["reader"],
                            "allowed_groups": ["engineering"],
                        }
                    }
                ]
            }
        }
    )

    response = await acl_module.get_document_acl(
        "roadmap.pdf",
        session_manager=FakeSessionManager(opensearch_client),
        user=FakeUser(),
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "owner": "owner",
        "allowed_users": ["reader"],
        "allowed_groups": ["engineering"],
    }
    search_body = opensearch_client.search.await_args.kwargs["body"]
    assert search_body["_source"] == ["owner", "allowed_users", "allowed_groups"]


def test_document_share_methods_are_not_exposed():
    from api import acl as acl_module

    assert not hasattr(acl_module, "share_document")
    assert not hasattr(acl_module, "unshare_document")
