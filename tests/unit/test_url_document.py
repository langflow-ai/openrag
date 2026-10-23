from connectors.url import crawler


def test_crawler_uses_scrapy_response_encoding_for_html_conversion(tmp_path):
    page_path = tmp_path / "page.html"
    page_path.write_bytes(b"<html><title>Caf\xe9</title><body>Caf\xe9</body></html>")

    page = crawler._page(
        {
            "canonical_url": "https://docs.example.com/cafe",
            "final_url": "https://docs.example.com/cafe",
            "depth": 1,
            "content_path": page_path.name,
            "encoding": "windows-1252",
        },
        tmp_path,
    )

    assert page.document is not None
    assert page.document.title == "Café"
    assert "Café" in page.document.markdown
