"""Plain-text files are chunked to size even when they have no blank lines."""

from src.utils.document_processing import process_text_file, split_to_size


def test_file_without_blank_lines_is_chunked_on_lines(tmp_path):
    lines = [f"第{i}行は日本の首都について説明する短い一文である。" for i in range(2000)]
    path = tmp_path / "wiki.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    chunks = process_text_file(str(path))["chunks"]

    assert len(chunks) > 1
    assert max(len(chunk["text"]) for chunk in chunks) <= 1000
    joined = "\n".join(chunk["text"] for chunk in chunks)
    assert all(line in joined for line in lines)


def test_paragraph_breaks_are_still_used_when_present(tmp_path):
    paragraphs = [f"Paragraph {i}. " + "word " * 40 for i in range(30)]
    path = tmp_path / "notes.txt"
    path.write_text("\n\n".join(paragraphs), encoding="utf-8")

    chunks = process_text_file(str(path))["chunks"]

    for chunk in chunks:
        assert all(
            part.strip() in [p.strip() for p in paragraphs] for part in chunk["text"].split("\n\n")
        )


def test_split_to_size_prefers_sentences_over_hard_cuts():
    text = "".join(f"これは{i}番目の文です。" for i in range(200))

    pieces = split_to_size(text, 100)

    assert max(len(piece) for piece in pieces) <= 100
    assert "".join(pieces) == text
    assert all(piece.endswith("。") for piece in pieces)


def test_split_to_size_hard_cuts_text_with_no_boundaries():
    pieces = split_to_size("x" * 2500, 1000)

    assert [len(piece) for piece in pieces] == [1000, 1000, 500]
