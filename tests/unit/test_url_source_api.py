from connectors.url.api import CreateSourceBody


def test_create_source_body_keeps_change_detection_outside_crawl_spec():
    body = CreateSourceBody(
        name="Documentation",
        starting_url="https://docs.example.com/",
        change_detection="always_reingest",
    )

    assert body.change_detection == "always_reingest"
    crawl_settings = body.spec().as_dict()
    assert crawl_settings["seed_url"] == "https://docs.example.com/"
    assert "change_detection" not in crawl_settings


def test_create_source_body_defaults_to_normalized_content_hash():
    body = CreateSourceBody(name="Documentation", starting_url="https://docs.example.com/")

    assert body.change_detection == "normalized_content_hash"
