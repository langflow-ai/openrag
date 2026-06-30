"""Seed the local Azurite emulator with test containers + blobs.

Run from the repo root with the project venv:
    uv run python scripts/connectors/azure/seed_azurite.py

Pass --reset to delete and recreate the containers before uploading:
    uv run python scripts/connectors/azure/seed_azurite.py --reset

Two containers are seeded:
    * CONTAINER_1 ("openrag-test-1") — plain text, markdown, and a PDF.
    * CONTAINER_2 ("openrag-test-2") — Office/web document formats
      (docx, xlsx, pptx, csv, html) for exercising the parser end to end.

The Office formats (docx/xlsx/pptx) are built as minimal-but-valid OOXML
packages in pure Python with `zipfile`, matching the no-external-deps style
of the PDF builder below.

Assumes `make azurite-up` is running (Azurite on localhost:10000).
"""

import argparse
import io
import zipfile

from azure.storage.blob import BlobServiceClient

# Well-known Azurite dev connection string. From the host this resolves to
# http://127.0.0.1:10000/devstoreaccount1.
CONN = "UseDevelopmentStorage=true"

CONTAINER_1 = "openrag-test-1"
CONTAINER_2 = "openrag-test-2"


def _make_sample_pdf() -> bytes:
    """Build a minimal valid single-page PDF in pure Python (no external deps)."""

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    title = "Fascinating Facts about Azure"
    body_lines = [
        "- The Naming Process: Microsoft originally wanted a name containing",
        '  "cloud". After being advised against it, they chose "Azure"',
        "  (a shade of blue) to represent the blue sky behind clouds.",
        '  Clients initially called the name a "dumb idea".',
        "",
        "- Space Travel & Datacenters: Microsoft Azure runs an extension of its",
        "  cloud called Azure Orbital, which allows satellite operators to",
        "  communicate with their spacecraft directly from Azure datacenters.",
        "",
        "- Massive Infrastructure: The network features over 175,000 miles of",
        "  terrestrial and subsea fiber-optic cables and operates in more regions",
        "  worldwide than any other cloud provider.",
        "",
        "- Linux Friendly: Despite being built by Microsoft, over half of the",
        "  Virtual Machine workloads running on Azure are based on Linux,",
        "  reflecting a deep embrace of open-source technology.",
        "",
        "- Extreme Physical Secrecy: Azure's datacenters are so state-of-the-art",
        "  that their physical addresses are never publicly listed to ensure",
        "  maximum security.",
    ]

    stream_parts = [
        b"BT\n",
        b"14 TL\n",
        b"/F1 14 Tf\n",
        b"72 720 Td\n",
        f"({escape(title)}) Tj T*\n".encode(),
        b"() Tj T*\n",
        b"/F1 11 Tf\n",
    ]
    for line in body_lines:
        stream_parts.append(f"({escape(line)}) Tj T*\n".encode())
    stream_parts.append(b"ET\n")
    stream = b"".join(stream_parts)

    raw_objects: list[bytes] = [
        b"<</Type /Catalog /Pages 2 0 R>>",
        b"<</Type /Pages /Kids [3 0 R] /Count 1>>",
        (
            b"<</Type /Page /Parent 2 0 R"
            b" /MediaBox [0 0 612 792]"
            b" /Contents 4 0 R"
            b" /Resources <</Font <</F1 5 0 R>>>>>>"
            b">>"
        ),
        b"<</Length " + str(len(stream)).encode() + b">>\nstream\n" + stream + b"endstream",
        b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>",
    ]

    body = b"%PDF-1.4\n"
    offsets: list[int] = []
    for idx, obj in enumerate(raw_objects, start=1):
        offsets.append(len(body))
        body += f"{idx} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_pos = len(body)
    n = len(raw_objects) + 1
    # Each xref entry must be exactly 20 bytes: 10-digit offset, space, 5-digit gen,
    # space, status flag, space, newline.
    xref = f"xref\n0 {n}\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n"
    trailer = f"trailer\n<</Size {n} /Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF\n"

    return body + xref.encode() + trailer.encode()


def _xml_escape(text: str) -> str:
    """Escape text for safe inclusion in XML element content/attributes."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _zip_package(parts: dict[str, str]) -> bytes:
    """Pack a mapping of archive-path -> XML/text into an in-memory zip (OOXML)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in parts.items():
            zf.writestr(path, data)
    return buf.getvalue()


def _col_letter(idx: int) -> str:
    """Convert a 0-based column index to a spreadsheet column letter (A, B, ...)."""
    letters = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _make_docx(title: str, paragraphs: list[str]) -> bytes:
    """Build a minimal-but-valid .docx (WordprocessingML) in pure Python."""
    body_parts = [
        '<w:p><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr>'
        f'<w:t xml:space="preserve">{_xml_escape(title)}</w:t></w:r></w:p>'
    ]
    for para in paragraphs:
        body_parts.append(
            f'<w:p><w:r><w:t xml:space="preserve">{_xml_escape(para)}</w:t></w:r></w:p>'
        )

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(body_parts) + "<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    return _zip_package(
        {
            "[Content_Types].xml": content_types,
            "_rels/.rels": rels,
            "word/document.xml": document,
        }
    )


def _make_xlsx(sheet_name: str, rows: list[list[str]]) -> bytes:
    """Build a minimal-but-valid .xlsx (SpreadsheetML) with inline-string cells."""
    row_xml = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_col_letter(c)}{r}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">'
                f"{_xml_escape(value)}</t></is></c>"
            )
        row_xml.append(f'<row r="{r}">' + "".join(cells) + "</row>")

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(row_xml) + "</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    return _zip_package(
        {
            "[Content_Types].xml": content_types,
            "_rels/.rels": rels,
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": workbook_rels,
            "xl/worksheets/sheet1.xml": sheet,
        }
    )


def _pptx_theme() -> str:
    """Return a minimal theme1.xml required by a valid .pptx package."""
    ph = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = '<a:ln w="{w}"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'name="Office Theme"><a:themeElements>'
        '<a:clrScheme name="Office">'
        '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
        '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
        '<a:dk2><a:srgbClr val="44546A"/></a:dk2>'
        '<a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>'
        '<a:accent1><a:srgbClr val="4472C4"/></a:accent1>'
        '<a:accent2><a:srgbClr val="ED7D31"/></a:accent2>'
        '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>'
        '<a:accent4><a:srgbClr val="FFC000"/></a:accent4>'
        '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>'
        '<a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
        '<a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
        '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink>'
        "</a:clrScheme>"
        '<a:fontScheme name="Office">'
        '<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/>'
        '<a:cs typeface=""/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/>'
        '<a:cs typeface=""/></a:minorFont>'
        "</a:fontScheme>"
        '<a:fmtScheme name="Office">'
        f"<a:fillStyleLst>{ph}{ph}{ph}</a:fillStyleLst>"
        "<a:lnStyleLst>"
        + line.format(w="6350")
        + line.format(w="12700")
        + line.format(w="19050")
        + "</a:lnStyleLst>"
        "<a:effectStyleLst>"
        "<a:effectStyle><a:effectLst/></a:effectStyle>"
        "<a:effectStyle><a:effectLst/></a:effectStyle>"
        "<a:effectStyle><a:effectLst/></a:effectStyle>"
        "</a:effectStyleLst>"
        f"<a:bgFillStyleLst>{ph}{ph}{ph}</a:bgFillStyleLst>"
        "</a:fmtScheme>"
        "</a:themeElements></a:theme>"
    )


def _make_pptx(title: str, bullets: list[str]) -> bytes:
    """Build a minimal-but-valid single-slide .pptx (PresentationML) in pure Python."""
    p_ns = (
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    )

    bullet_paras = "".join(f"<a:p><a:r><a:t>{_xml_escape(b)}</a:t></a:r></a:p>" for b in bullets)
    slide = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<p:sld {p_ns}><p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        "<p:sp><p:nvSpPr>"
        '<p:cNvPr id="2" name="Title 1"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
        "<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p><a:r><a:t>{_xml_escape(title)}</a:t></a:r></a:p></p:txBody></p:sp>"
        "<p:sp><p:nvSpPr>"
        '<p:cNvPr id="3" name="Content 2"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
        "<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>"
        f"{bullet_paras}</p:txBody></p:sp>"
        "</p:spTree></p:cSld></p:sld>"
    )
    slide_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/>'
        "</Relationships>"
    )
    slide_layout = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sldLayout {p_ns} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/></p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"
    )
    slide_layout_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
        'Target="../slideMasters/slideMaster1.xml"/>'
        "</Relationships>"
    )
    slide_master = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<p:sldMaster {p_ns}><p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/></p:spTree></p:cSld>"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" '
        'accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" '
        'accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        "</p:sldMaster>"
    )
    slide_master_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
        'Target="../theme/theme1.xml"/>'
        "</Relationships>"
    )
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<p:presentation {p_ns}>"
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
        '<p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )
    presentation_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        'Target="slides/slide1.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
        'Target="theme/theme1.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="ppt/presentation.xml"/>'
        "</Relationships>"
    )
    return _zip_package(
        {
            "[Content_Types].xml": content_types,
            "_rels/.rels": rels,
            "ppt/presentation.xml": presentation,
            "ppt/_rels/presentation.xml.rels": presentation_rels,
            "ppt/slides/slide1.xml": slide,
            "ppt/slides/_rels/slide1.xml.rels": slide_rels,
            "ppt/slideLayouts/slideLayout1.xml": slide_layout,
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": slide_layout_rels,
            "ppt/slideMasters/slideMaster1.xml": slide_master,
            "ppt/slideMasters/_rels/slideMaster1.xml.rels": slide_master_rels,
            "ppt/theme/theme1.xml": _pptx_theme(),
        }
    )


_AZURE_FACTS = [
    "Microsoft originally wanted a cloud name containing the word 'cloud' before "
    "settling on 'Azure', the shade of blue of the sky behind the clouds.",
    "Azure Orbital lets satellite operators communicate with their spacecraft "
    "directly from Azure datacenters.",
    "The Azure network spans over 175,000 miles of terrestrial and subsea "
    "fiber-optic cable and operates in more regions than any other cloud provider.",
    "Over half of all virtual machine workloads running on Azure are Linux-based.",
    "Azure datacenter physical addresses are never publicly listed for security.",
]


_WORD_DOC = _make_docx(
    "Fascinating Facts about Azure",
    [
        "This Word document was ingested from the local Azurite emulator to "
        "verify the OpenRAG Azure Blob connector handles .docx files end to end.",
        *_AZURE_FACTS,
    ],
)

_EXCEL_DOC = _make_xlsx(
    "Azure Facts",
    [
        ["Service", "Category", "Fact"],
        ["Azure Orbital", "Space", "Talk to spacecraft from Azure datacenters."],
        ["Global Network", "Infrastructure", "175,000+ miles of fiber-optic cable."],
        ["Virtual Machines", "Compute", "Over half of VM workloads run Linux."],
        ["Datacenters", "Security", "Physical addresses are never publicly listed."],
    ],
)

_POWERPOINT_DOC = _make_pptx(
    "Fascinating Facts about Azure",
    _AZURE_FACTS,
)

_CSV_DOC = (
    b"Service,Category,Fact\r\n"
    b"Azure Orbital,Space,Talk to spacecraft from Azure datacenters.\r\n"
    b"Global Network,Infrastructure,175000+ miles of fiber-optic cable.\r\n"
    b"Virtual Machines,Compute,Over half of VM workloads run Linux.\r\n"
    b"Datacenters,Security,Physical addresses are never publicly listed.\r\n"
)

_HTML_DOC = (
    b"<!DOCTYPE html>\n"
    b'<html lang="en">\n<head>\n<meta charset="utf-8"/>\n'
    b"<title>Fascinating Facts about Azure</title>\n</head>\n<body>\n"
    b"<h1>Fascinating Facts about Azure</h1>\n"
    b"<p>This HTML file was ingested from the local Azurite emulator to verify "
    b"the OpenRAG Azure Blob connector handles .html files end to end.</p>\n"
    b"<ul>\n"
    b"<li>Microsoft chose the name 'Azure' for the blue sky behind the clouds.</li>\n"
    b"<li>Azure Orbital connects satellite operators to spacecraft from datacenters.</li>\n"
    b"<li>The network spans over 175,000 miles of fiber-optic cable.</li>\n"
    b"<li>Over half of Azure VM workloads run Linux.</li>\n"
    b"<li>Datacenter physical addresses are never publicly listed.</li>\n"
    b"</ul>\n</body>\n</html>\n"
)


# Container 1: plain text, markdown, PDF.
BLOBS_1 = {
    "azure-blob-text.txt": b"Hello from Azurite! OpenRAG Azure Blob connector test document.\n",
    "notes/azure-blob-markdown.md": (
        b"# Azure Blob Connector\n\n"
        b"This markdown blob was ingested from the local Azurite emulator "
        b"to verify the OpenRAG Azure Blob connector end to end.\n\n"
        b"Microsoft Azure is a massive global cloud platform offering over 200 services. "
        b"It powers 95% of Fortune 500 companies and is connected by enough fiber-optic cable "
        b"to stretch to the Moon and back three times.\n"
    ),
    "docs/azure-blob-portal-document.pdf": _make_sample_pdf(),
}

# Container 1, "VERSION_2" updates: the same two text/markdown blobs as BLOBS_1
# above, re-tagged with a "VERSION_2" identifier so re-ingestion / change
# detection can be exercised via `--update`.
BLOBS_1_V2 = {
    "azure-blob-text.txt": (
        b"Hello from Azurite! OpenRAG Azure Blob connector test document. VERSION_2\n"
    ),
    "notes/azure-blob-markdown.md": (
        b"# Azure Blob Connector (VERSION_2)\n\n"
        b"This markdown blob was ingested from the local Azurite emulator "
        b"to verify the OpenRAG Azure Blob connector end to end.\n\n"
        b"Microsoft Azure is a massive global cloud platform offering over 200 services. "
        b"It powers 95% of Fortune 500 companies and is connected by enough fiber-optic cable "
        b"to stretch to the Moon and back three times.\n"
    ),
}

# Container 2: Office / web document formats.
BLOBS_2 = {
    "docs/azure-blob-word.docx": _WORD_DOC,
    "spreadsheets/azure-blob-excel.xlsx": _EXCEL_DOC,
    "presentations/azure-blob-powerpoint.pptx": _POWERPOINT_DOC,
    "spreadsheets/azure-blob-comma-separated.csv": _CSV_DOC,
    "azure-blob-hypertext-markup.html": _HTML_DOC,
}


def _seed_container(
    svc: BlobServiceClient, name: str, blobs: dict[str, bytes], reset: bool
) -> None:
    """Create (optionally resetting) a container and upload the given blobs."""
    container = svc.get_container_client(name)

    if reset:
        try:
            container.delete_container()
            print(f"Deleted existing container {name!r}.")
        except Exception as exc:  # ResourceNotFoundError if it didn't exist
            print(f"Container {name!r} did not exist ({type(exc).__name__}), skipping delete.")

    print(f"Ensuring container {name!r} exists...")
    try:
        container.create_container()
        print("  created.")
    except Exception as exc:  # ResourceExistsError on re-run
        print(f"  already exists ({type(exc).__name__}).")

    for blob_name, data in blobs.items():
        print(f"Uploading blob {blob_name!r} ({len(data)} bytes)...")
        container.get_blob_client(blob_name).upload_blob(data, overwrite=True)

    print(f"\nDone. Blobs in container {name!r}:")
    for b in container.list_blobs():
        print(f"  - {b.name} ({b.size} bytes)")


def _update_blobs(svc: BlobServiceClient, name: str, blobs: dict[str, bytes]) -> None:
    """Overwrite specific blobs in an existing container (no create/delete)."""
    container = svc.get_container_client(name)
    for blob_name, data in blobs.items():
        print(f"Updating blob {blob_name!r} ({len(data)} bytes)...")
        container.get_blob_client(blob_name).upload_blob(data, overwrite=True)

    print(f"\nDone. Updated {len(blobs)} blob(s) in container {name!r}:")
    for blob_name in blobs:
        print(f"  - {blob_name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--reset", action="store_true", help="Delete the containers before seeding."
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            'Update the "azure-blob-text.txt" and "notes/azure-blob-markdown.md" '
            f'blobs in {CONTAINER_1!r} in place with a "VERSION_2" identifier, then exit.'
        ),
    )
    args = parser.parse_args()

    print("Connecting to Azurite...")
    svc = BlobServiceClient.from_connection_string(CONN)

    if args.update:
        _update_blobs(svc, CONTAINER_1, BLOBS_1_V2)
        return

    _seed_container(svc, CONTAINER_1, BLOBS_1, args.reset)
    print()
    _seed_container(svc, CONTAINER_2, BLOBS_2, args.reset)


if __name__ == "__main__":
    main()
