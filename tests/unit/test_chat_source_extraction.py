from types import SimpleNamespace

import pytest

import agent
from api.v1.chat import _extract_sources as extract_stream_sources


class _ResponseWithModelDump:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


@pytest.mark.asyncio
async def test_async_langflow_chat_extracts_nested_tool_sources(monkeypatch):
    response_payload = {
        "outputs": {
            "message": {
                "data": {
                    "content_blocks": [
                        {
                            "contents": [
                                {
                                    "type": "tool_use",
                                    "name": "search_documents",
                                    "output": [
                                        {
                                            "text_key": "text",
                                            "data": {
                                                "text": "Purple elephants dancing in the moonlight.",
                                                "filename": "sdk_test_doc.md",
                                                "score": 0.98,
                                                "page": 1,
                                                "mimetype": "text/markdown",
                                            },
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            }
        }
    }

    async def fake_async_response(*args, **kwargs):
        return (
            'The document mentions "purple elephants dancing."',
            "response-123",
            _ResponseWithModelDump(response_payload),
        )

    monkeypatch.setattr(agent, "async_response", fake_async_response)

    response_text, response_id, sources = await agent.async_langflow_chat(
        langflow_client=SimpleNamespace(),
        flow_id="flow-id",
        prompt="What color are the dancing animals?",
        user_id="test-user",
        store_conversation=False,
    )

    assert response_id == "response-123"
    assert "purple elephants" in response_text
    assert sources == [
        {
            "filename": "sdk_test_doc.md",
            "text": "Purple elephants dancing in the moonlight.",
            "score": 0.98,
            "page": 1,
            "mimetype": "text/markdown",
        }
    ]


@pytest.mark.asyncio
async def test_async_langflow_chat_extracts_filenames_from_summary_text(monkeypatch):
    response_text = """
    Here are some retrieved documents related to your request.

    1. **SDK Integration Test Document**
       - Contains unique content about purple elephants dancing.
       - Files: `sdk_test_doc_ae361e43.md`, `sdk_test_doc_b7e33f07.md`
    """.strip()

    response_payload = {
        "outputs": {
            "message": {
                "message": response_text,
            }
        }
    }

    async def fake_async_response(*args, **kwargs):
        return (response_text, "response-456", _ResponseWithModelDump(response_payload))

    monkeypatch.setattr(agent, "async_response", fake_async_response)

    _, _, sources = await agent.async_langflow_chat(
        langflow_client=SimpleNamespace(),
        flow_id="flow-id",
        prompt="What documents mention dancing animals?",
        user_id="test-user",
        store_conversation=False,
    )

    assert [source["filename"] for source in sources] == [
        "sdk_test_doc_ae361e43.md",
        "sdk_test_doc_b7e33f07.md",
    ]
    assert all(source["text"] == "" for source in sources)


def test_stream_source_extraction_extracts_filenames_from_summary_text():
    item = {
        "results": [
            {
                "text": (
                    "SDK Integration Test Document\n"
                    "- Files: `sdk_test_doc_ae361e43.md`, `sdk_test_doc_b7e33f07.md`"
                )
            }
        ]
    }

    assert extract_stream_sources(item) == [
        {
            "filename": "sdk_test_doc_ae361e43.md",
            "text": "",
            "score": 0,
            "page": None,
            "mimetype": None,
        },
        {
            "filename": "sdk_test_doc_b7e33f07.md",
            "text": "",
            "score": 0,
            "page": None,
            "mimetype": None,
        },
    ]
