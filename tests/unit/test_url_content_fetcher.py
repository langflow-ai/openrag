from utils.url_content_fetcher import VisibleTextHTMLParser


def test_visible_text_parser_excludes_script_and_style_content():
    parser = VisibleTextHTMLParser()

    parser.feed("<style>body { color: red; }</style><script>track()</script><p>Body</p>")
    parser.close()

    assert parser.get_text() == "Body"
