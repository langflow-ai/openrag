"""Seed the local Azurite emulator with a test container + blobs.

Run from the repo root with the project venv:
    uv run python scripts/connectors/azure/seed_azurite.py

Pass --reset to delete and recreate the container before uploading:
    uv run python scripts/connectors/azure/seed_azurite.py --reset

Assumes `make azurite-up` is running (Azurite on localhost:10000).
"""

import argparse

from azure.storage.blob import BlobServiceClient

# Well-known Azurite dev connection string. From the host this resolves to
# http://127.0.0.1:10000/devstoreaccount1.
CONN = "UseDevelopmentStorage=true"

CONTAINER = "openrag-test"


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


BLOBS = {
    "azure-test-text-format.txt": b"Hello from Azurite! OpenRAG Azure Blob connector test document.\n",
    "notes/azure-test-markdown-format.md": (
        b"# Azure Blob Connector\n\n"
        b"This markdown blob was ingested from the local Azurite emulator "
        b"to verify the OpenRAG Azure Blob connector end to end.\n\n"
        b"Microsoft Azure is a massive global cloud platform offering over 200 services. "
        b"It powers 95% of Fortune 500 companies and is connected by enough fiber-optic cable "
        b"to stretch to the Moon and back three times.\n"
    ),
    "docs/azure-test-portal-document-format.pdf": _make_sample_pdf(),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reset", action="store_true", help="Delete the container before seeding.")
    args = parser.parse_args()

    print("Connecting to Azurite...")
    svc = BlobServiceClient.from_connection_string(CONN)
    container = svc.get_container_client(CONTAINER)

    if args.reset:
        try:
            container.delete_container()
            print(f"Deleted existing container {CONTAINER!r}.")
        except Exception as exc:  # ResourceNotFoundError if it didn't exist
            print(f"Container {CONTAINER!r} did not exist ({type(exc).__name__}), skipping delete.")

    print(f"Ensuring container {CONTAINER!r} exists...")
    try:
        container.create_container()
        print("  created.")
    except Exception as exc:  # ResourceExistsError on re-run
        print(f"  already exists ({type(exc).__name__}).")

    for name, data in BLOBS.items():
        print(f"Uploading blob {name!r} ({len(data)} bytes)...")
        container.get_blob_client(name).upload_blob(data, overwrite=True)

    print("\nDone. Blobs in container:")
    for b in container.list_blobs():
        print(f"  - {b.name} ({b.size} bytes)")


if __name__ == "__main__":
    main()
