from agent import _extract_retrieval_sources


def test_extract_retrieval_sources_from_langflow_tool_use_content_block():
    response = {
        "outputs": [
            {
                "results": {
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
                                                    "text": "purple elephants dancing",
                                                    "filename": "sdk_test_doc.md",
                                                    "mimetype": "text/markdown",
                                                    "page": 0,
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
        ]
    }

    assert _extract_retrieval_sources(response) == [
        {
            "filename": "sdk_test_doc.md",
            "text": "purple elephants dancing",
            "score": 0,
            "page": 0,
            "mimetype": "text/markdown",
        }
    ]


def test_extract_retrieval_sources_ignores_assistant_message_text():
    response = {
        "outputs": [
            {
                "results": {
                    "message": {
                        "data": {
                            "text": "The document says the animals are purple.",
                            "content_blocks": [],
                        }
                    }
                }
            }
        ]
    }

    assert _extract_retrieval_sources(response) == []
