from typing import Any

from docling_core.types.doc import ImageRefMode

from lfx.base.data.docling_utils import extract_docling_documents
from lfx.custom import Component
from lfx.io import DropdownInput, HandleInput, MessageTextInput, Output, StrInput
from lfx.schema import Data, DataFrame


class ExportDoclingDocumentComponent(Component):
    display_name: str = "Export DoclingDocument"
    description: str = "Export DoclingDocument to markdown, html or other formats."
    documentation = "https://docling-project.github.io/docling/"
    icon = "Docling"
    name = "ExportDoclingDocument"

    inputs = [
        HandleInput(
            name="data_inputs",
            display_name="JSON or Table",
            info="The data with documents to export.",
            input_types=["Data", "JSON", "DataFrame", "Table"],
            required=True,
        ),
        DropdownInput(
            name="export_format",
            display_name="Export format",
            options=["Markdown", "HTML", "Plaintext", "DocTags"],
            info="Select the export format to convert the input.",
            value="Markdown",
            real_time_refresh=True,
        ),
        DropdownInput(
            name="image_mode",
            display_name="Image export mode",
            options=["placeholder", "embedded"],
            info=(
                "Specify how images are exported in the output. Placeholder will replace the images with a string, "
                "whereas Embedded will include them as base64 encoded images."
            ),
            value="placeholder",
        ),
        StrInput(
            name="md_image_placeholder",
            display_name="Image placeholder",
            info="Specify the image placeholder for markdown exports.",
            value="<!-- image -->",
            advanced=True,
        ),
        StrInput(
            name="md_page_break_placeholder",
            display_name="Page break placeholder",
            info="Add this placeholder between pages in the markdown output.",
            value="",
            advanced=True,
        ),
        MessageTextInput(
            name="doc_key",
            display_name="Doc Key",
            info="The key to use for the DoclingDocument column.",
            value="doc",
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Exported data", name="data", method="export_document"),
        Output(display_name="Table", name="dataframe", method="as_dataframe"),
    ]

    def update_build_config(self, build_config: dict, field_value: Any, field_name: str | None = None) -> dict:
        if field_name == "export_format" and field_value == "Markdown":
            build_config["md_image_placeholder"]["show"] = True
            build_config["md_page_break_placeholder"]["show"] = True
            build_config["image_mode"]["show"] = True
        elif field_name == "export_format" and field_value == "HTML":
            build_config["md_image_placeholder"]["show"] = False
            build_config["md_page_break_placeholder"]["show"] = False
            build_config["image_mode"]["show"] = True
        elif field_name == "export_format" and field_value in {"Plaintext", "DocTags"}:
            build_config["md_image_placeholder"]["show"] = False
            build_config["md_page_break_placeholder"]["show"] = False
            build_config["image_mode"]["show"] = False

        return build_config

    def _base_metadata(self, doc) -> dict:
        """Build shared metadata from a DoclingDocument."""
        metadata: dict = {"export_format": self.export_format}
        if hasattr(doc, "name") and doc.name:
            metadata["name"] = doc.name
        if hasattr(doc, "origin") and doc.origin is not None:
            if hasattr(doc.origin, "filename") and doc.origin.filename:
                metadata["filename"] = doc.origin.filename
            if hasattr(doc.origin, "binary_hash") and doc.origin.binary_hash:
                metadata["document_id"] = str(doc.origin.binary_hash)
            if hasattr(doc.origin, "mimetype") and doc.origin.mimetype:
                metadata["mimetype"] = doc.origin.mimetype
        return metadata

    def _export_per_page_markdown(self, doc, image_mode: ImageRefMode, base_meta: dict) -> list[Data]:
        """Export one Data chunk per page, tagging each with page=N.

        Uses DoclingDocument.pages (ordered dict of page_no -> PageItem) to
        iterate pages.
        """
        pages_dict = getattr(doc, "pages", None)
        if not pages_dict:
            return []

        results: list[Data] = []
        for page_no in sorted(pages_dict.keys()):
            try:
                try:
                    # Try standard page_no first (docling-core 2.x+)
                    page_content = doc.export_to_markdown(
                        image_mode=image_mode,
                        image_placeholder=self.md_image_placeholder,
                        page_no=page_no,
                    )
                except TypeError:
                    # Fallback to from_page/to_page parameters
                    page_content = doc.export_to_markdown(
                        image_mode=image_mode,
                        image_placeholder=self.md_image_placeholder,
                        from_page=page_no,
                        to_page=page_no,
                    )
            except Exception:
                # Any exception from either attempt: fall back to whole-document export
                return []

            if page_content and page_content.strip():
                meta = {**base_meta, "page": int(page_no)}
                results.append(Data(text=page_content, data={"text": page_content, **meta}))

        return results

    def export_document(self) -> list[Data]:
        documents, warning = extract_docling_documents(self.data_inputs, self.doc_key)
        if warning:
            self.status = warning

        results: list[Data] = []
        try:
            image_mode = ImageRefMode(self.image_mode)
            for doc in documents:
                base_meta = self._base_metadata(doc)

                # For Markdown: attempt per-page export so downstream chunks
                # carry an accurate page number (used by the chat citation UI).
                if self.export_format == "Markdown":
                    per_page = self._export_per_page_markdown(doc, image_mode, base_meta)
                    if per_page:
                        results.extend(per_page)
                        continue

                    # Fall back to whole-document export (no page granularity)
                    try:
                        content = doc.export_to_markdown(
                            image_mode=image_mode,
                            image_placeholder=self.md_image_placeholder,
                            page_break_placeholder=self.md_page_break_placeholder,
                        )
                    except TypeError:
                        # Older docling-core versions lack page_break_placeholder
                        content = doc.export_to_markdown(
                            image_mode=image_mode,
                            image_placeholder=self.md_image_placeholder,
                        )
                elif self.export_format == "HTML":
                    content = doc.export_to_html(image_mode=image_mode)
                elif self.export_format == "Plaintext":
                    content = doc.export_to_text()
                elif self.export_format == "DocTags":
                    content = doc.export_to_doctags()
                else:
                    content = ""

                results.append(Data(text=content, data={"text": content, **base_meta}))

        except Exception as e:
            msg = f"Error exporting DoclingDocument: {e}"
            raise TypeError(msg) from e

        return results

    def as_dataframe(self) -> DataFrame:
        return DataFrame(self.export_document())
