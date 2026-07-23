import importlib
import io
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from langchain_community.document_loaders import RecursiveUrlLoader
from markitdown import MarkItDown

from lfx.custom.custom_component.component import Component
from lfx.field_typing.range_spec import RangeSpec
from lfx.helpers.data import safe_convert
from lfx.io import BoolInput, DropdownInput, IntInput, MessageTextInput, Output, SliderInput, StrInput, TableInput
from lfx.log.logger import logger
from lfx.schema.dataframe import DataFrame
from lfx.schema.message import Message
from lfx.utils.request_utils import get_user_agent
from lfx.utils.ssrf_protection import SSRFProtectionError, validate_url_for_ssrf

# Constants
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_DEPTH = 1
DEFAULT_FORMAT = "Text"


URL_REGEX = re.compile(
    r"^(https?:\/\/)?" r"(www\.)?" r"([a-zA-Z0-9.-]+)" r"(\.[a-zA-Z]{2,})?" r"(:\d+)?" r"(\/[^\s]*)?$",
    re.IGNORECASE,
)

USER_AGENT = None
# Check if langflow is installed using importlib.util.find_spec(name))
if importlib.util.find_spec("langflow"):
    langflow_installed = True
    USER_AGENT = get_user_agent()
else:
    langflow_installed = False
    USER_AGENT = "lfx"


# VULN-13906 destination allowlist + IP-range check. Mirrors src/utils/ssrf_guard.py —
# this embedded Langflow component can't import repo modules at flow runtime, so the
# logic is duplicated here (kept in sync via tests/unit/test_flow_url_intent_gate.py).
# Read as a plain container env var (static deployment config, not per-request), set
# alongside the backend's OPENRAG_URL_INGEST_ALLOWED_HOSTS on the langflow container.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _openrag_allowed_hosts() -> set:
    raw = os.environ.get("OPENRAG_URL_INGEST_ALLOWED_HOSTS", "").strip()
    if not raw:
        return set()
    return {v.strip() for v in raw.split(",") if v.strip()}


def _openrag_is_host_allowlisted(host: str) -> bool:
    allowed = _openrag_allowed_hosts()
    if not allowed:
        return False
    host = host.strip().lower().rstrip(".")
    for entry in allowed:
        entry = entry.strip().lower().rstrip(".")
        if not entry:
            continue
        if entry.startswith("*."):
            if host == entry[2:] or host.endswith(entry[1:]):
                return True
        elif host == entry:
            return True
    return False


def _openrag_is_unsafe_ip(ip) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_multicast or ip.is_unspecified:
        return True
    return isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK


def _openrag_assert_url_ingest_allowed(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        msg = f"URL ingestion blocked: could not parse a host from {url!r}"
        raise ValueError(msg)

    if not _openrag_is_host_allowlisted(host):
        msg = f"URL ingestion blocked: host '{host}' is not in OPENRAG_URL_INGEST_ALLOWED_HOSTS."
        raise ValueError(msg)

    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(r[4][0]) for r in socket.getaddrinfo(host, None)]
        except OSError as exc:
            msg = f"Could not resolve host: {host}"
            raise ValueError(msg) from exc

    for ip in ips:
        if _openrag_is_unsafe_ip(ip):
            msg = (
                f"URL ingestion blocked: {host} resolves to a non-routable/internal "
                f"address ({ip}), which is never allowed regardless of the host allowlist."
            )
            raise ValueError(msg)


class URLComponent(Component):
    """A component that loads and parses content from web pages recursively.

    This component allows fetching content from one or more URLs, with options to:
    - Control crawl depth
    - Prevent crawling outside the root domain
    - Use async loading for better performance
    - Extract either raw HTML or clean text
    - Configure request headers and timeouts
    """

    display_name = "URL"
    description = "Fetch content from one or more web pages, following links recursively."
    documentation: str = "https://docs.langflow.org/url"
    icon = "layout-template"
    name = "URLComponent"

    # VULN-13906: backend-injected trusted value (see chat_service.py
    # X-Langflow-Global-Var-OPENRAG_CURRENT_USER_MESSAGE), never model-supplied.
    # Used to gate chat-invoked fetches on the real user's current message so a
    # document-embedded instruction can't drive this tool on its own.
    _openrag_global_placeholders = {
        "openrag_current_user_message": "OPENRAG_CURRENT_USER_MESSAGE",
    }

    inputs = [
        MessageTextInput(
            name="urls",
            display_name="URLs",
            info="Enter one or more URLs to crawl recursively, by clicking the '+' button.",
            is_list=True,
            tool_mode=True,
            placeholder="Enter a URL...",
            list_add_label="Add URL",
            input_types=["Message"],
        ),
        SliderInput(
            name="max_depth",
            display_name="Depth",
            info=(
                "Controls how many 'clicks' away from the initial page the crawler will go:\n"
                "- depth 1: only the initial page\n"
                "- depth 2: initial page + all pages linked directly from it\n"
                "- depth 3: initial page + direct links + links found on those direct link pages\n"
                "Note: This is about link traversal, not URL path depth."
            ),
            value=DEFAULT_MAX_DEPTH,
            range_spec=RangeSpec(min=1, max=5, step=1),
            required=False,
            min_label=" ",
            max_label=" ",
            min_label_icon="None",
            max_label_icon="None",
            # slider_input=True
        ),
        BoolInput(
            name="prevent_outside",
            display_name="Prevent Outside",
            info=(
                "If enabled, only crawls URLs within the same domain as the root URL. "
                "This helps prevent the crawler from going to external websites."
            ),
            value=True,
            required=False,
            advanced=True,
        ),
        BoolInput(
            name="use_async",
            display_name="Use Async",
            info=(
                "If enabled, uses asynchronous loading which can be significantly faster "
                "but might use more system resources."
            ),
            value=True,
            required=False,
            advanced=True,
        ),
        DropdownInput(
            name="format",
            display_name="Output Format",
            info=(
                "Output Format. Use 'Text' to extract the text from the HTML, "
                "'Markdown' to parse the HTML into Markdown format, or 'HTML' "
                "for the raw HTML content."
            ),
            options=["Text", "HTML", "Markdown"],
            value=DEFAULT_FORMAT,
            advanced=True,
        ),
        IntInput(
            name="timeout",
            display_name="Timeout",
            info="Timeout for the request in seconds.",
            value=DEFAULT_TIMEOUT,
            required=False,
            advanced=True,
        ),
        TableInput(
            name="headers",
            display_name="Headers",
            info="The headers to send with the request",
            table_schema=[
                {
                    "name": "key",
                    "display_name": "Header",
                    "type": "str",
                    "description": "Header name",
                },
                {
                    "name": "value",
                    "display_name": "Value",
                    "type": "str",
                    "description": "Header value",
                },
            ],
            value=[{"key": "User-Agent", "value": USER_AGENT}],
            advanced=True,
            input_types=["DataFrame", "Table"],
        ),
        BoolInput(
            name="filter_text_html",
            display_name="Filter Text/HTML",
            info="If enabled, filters out text/css content type from the results.",
            value=True,
            required=False,
            advanced=True,
        ),
        BoolInput(
            name="continue_on_failure",
            display_name="Continue on Failure",
            info="If enabled, continues crawling even if some requests fail.",
            value=True,
            required=False,
            advanced=True,
        ),
        BoolInput(
            name="check_response_status",
            display_name="Check Response Status",
            info="If enabled, checks the response status of the request.",
            value=False,
            required=False,
            advanced=True,
        ),
        BoolInput(
            name="autoset_encoding",
            display_name="Autoset Encoding",
            info="If enabled, automatically sets the encoding of the request.",
            value=True,
            required=False,
            advanced=True,
        ),
        StrInput(
            name="openrag_current_user_message",
            display_name="OpenRAG Current User Message",
            value="OPENRAG_CURRENT_USER_MESSAGE",
            load_from_db=True,
            input_types=["Text", "Message"],
            advanced=True,
            info=(
                "Backend-injected trusted copy of the current chat user message. "
                "Used to verify a chat-invoked URL fetch reflects real user intent, "
                "not just a model tool-call argument."
            ),
        ),
    ]

    outputs = [
        Output(display_name="Extracted Pages", name="page_results", method="fetch_content"),
        Output(display_name="Raw Content", name="raw_results", method="fetch_content_as_message", tool_mode=False),
    ]

    @staticmethod
    def _html_extractor(x: str) -> str:
        """Extract raw HTML content."""
        return x

    @staticmethod
    def _text_extractor(x: str) -> str:
        """Extract clean text from HTML."""
        return BeautifulSoup(x, "lxml").get_text()

    @staticmethod
    def _markdown_extractor(x: str) -> str:
        """Convert HTML to Markdown format."""
        stream = io.BytesIO(x.encode("utf-8"))
        result = MarkItDown(enable_plugins=False).convert_stream(stream)
        return result.markdown

    @staticmethod
    def validate_url(url: str) -> bool:
        """Validates if the given string matches URL pattern.

        Args:
            url: The URL string to validate

        Returns:
            bool: True if the URL is valid, False otherwise
        """
        return bool(URL_REGEX.match(url))

    @staticmethod
    def _openrag_input_to_str(value) -> str:
        if value is None:
            return ""
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        if hasattr(value, "text"):
            value = value.text
        return str(value or "").strip()

    def _openrag_trusted_user_message(self) -> str:
        """Return the backend-injected trusted user message, or "" if not provided.

        Empty means this flow run has no chat-message context to check against
        (e.g. the Knowledge API's explicit URL-submit path, where the submission
        itself is the confirmed intent) — callers should only gate on this value
        when it is non-empty.
        """
        value = self._openrag_input_to_str(getattr(self, "openrag_current_user_message", ""))
        placeholder = self._openrag_global_placeholders.get("openrag_current_user_message")
        if value == placeholder:
            return ""
        return value

    def ensure_url(self, url: str) -> str:
        """Ensures the given string is a valid URL.

        Args:
            url: The URL string to validate and normalize

        Returns:
            str: The normalized URL

        Raises:
            ValueError: If the URL is invalid, doesn't reflect real user intent,
                or is blocked by SSRF protection
        """
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if not self.validate_url(url):
            msg = f"Invalid URL: {url}"
            raise ValueError(msg)

        # --- OPENRAG intent check ---
        # VULN-13906: a chat-invoked fetch is only allowed if the requested URL was
        # actually part of the real user's current message. This blocks a document's
        # injected instructions from driving the tool: the model may be tricked into
        # calling this tool, but the backend-known trusted message won't contain the
        # attacker's URL, so the fetch is refused before any request is made.
        trusted_user_message = self._openrag_trusted_user_message()
        if trusted_user_message and url not in trusted_user_message:
            msg = (
                "URL ingestion blocked: the requested URL was not found in the "
                "current user message. Only URLs the user explicitly typed can be fetched."
            )
            raise ValueError(msg)
        # --- end OPENRAG intent check ---

        # --- OPENRAG allowlist check ---
        # VULN-13906: every fetch (chat-invoked or Knowledge-API-submitted) must also
        # pass a fail-closed destination allowlist plus a full IP-range check, so an
        # allowlisted hostname later rebound (DNS rebinding) to a private/internal
        # address is still blocked. See src/utils/ssrf_guard.py for the backend-side
        # equivalent used by the non-chat ingestion path.
        _openrag_assert_url_ingest_allowed(url)
        # --- end OPENRAG allowlist check ---

        # SSRF Protection: Validate URL to prevent access to internal resources
        # Blocks requests to private IPs, localhost, and cloud metadata endpoints
        # when LANGFLOW_SSRF_PROTECTION_ENABLED=true
        try:
            validate_url_for_ssrf(url, warn_only=False)
        except SSRFProtectionError as e:
            msg = f"SSRF Protection: {e}"
            raise ValueError(msg) from e

        return url

    def _create_loader(self, url: str) -> RecursiveUrlLoader:
        """Creates a RecursiveUrlLoader instance with the configured settings.

        Args:
            url: The URL to load

        Returns:
            RecursiveUrlLoader: Configured loader instance
        """
        headers_dict = {header["key"]: header["value"] for header in self.headers if header["value"] is not None}
        extractors = {
            "HTML": self._html_extractor,
            "Markdown": self._markdown_extractor,
            "Text": self._text_extractor,
        }
        extractor = extractors.get(self.format, self._text_extractor)

        return RecursiveUrlLoader(
            url=url,
            max_depth=self.max_depth,
            prevent_outside=self.prevent_outside,
            use_async=self.use_async,
            extractor=extractor,
            timeout=self.timeout,
            headers=headers_dict,
            check_response_status=self.check_response_status,
            continue_on_failure=self.continue_on_failure,
            base_url=url,  # Add base_url to ensure consistent domain crawling
            autoset_encoding=self.autoset_encoding,  # Enable automatic encoding detection
            exclude_dirs=[],  # Allow customization of excluded directories
            link_regex=None,  # Allow customization of link filtering
        )

    def fetch_url_contents(self) -> list[dict]:
        """Load documents from the configured URLs.

        Returns:
            List[Data]: List of Data objects containing the fetched content

        Raises:
            ValueError: If no valid URLs are provided or if there's an error loading documents
        """
        try:
            urls = list({self.ensure_url(url) for url in self.urls if url.strip()})
            logger.debug(f"URLs: {urls}")
            if not urls:
                msg = "No valid URLs provided."
                raise ValueError(msg)

            all_docs = []
            for url in urls:
                logger.debug(f"Loading documents from {url}")

                try:
                    loader = self._create_loader(url)
                    docs = loader.load()

                    if not docs:
                        logger.warning(f"No documents found for {url}")
                        continue

                    logger.debug(f"Found {len(docs)} documents from {url}")
                    all_docs.extend(docs)

                except requests.exceptions.RequestException as e:
                    logger.exception(f"Error loading documents from {url}: {e}")
                    continue

            if not all_docs:
                msg = "No documents were successfully loaded from any URL"
                raise ValueError(msg)

            # data = [Data(text=doc.page_content, **doc.metadata) for doc in all_docs]
            data = [
                {
                    "text": safe_convert(doc.page_content, clean_data=True),
                    "url": doc.metadata.get("source", ""),
                    "title": doc.metadata.get("title", ""),
                    "description": doc.metadata.get("description", ""),
                    "content_type": doc.metadata.get("content_type", ""),
                    "language": doc.metadata.get("language", ""),
                }
                for doc in all_docs
            ]
        except Exception as e:
            error_msg = e.message if hasattr(e, "message") else e
            msg = f"Error loading documents: {error_msg!s}"
            logger.exception(msg)
            raise ValueError(msg) from e
        return data

    def fetch_content(self) -> DataFrame:
        """Convert the documents to a DataFrame."""
        return DataFrame(data=self.fetch_url_contents())

    def fetch_content_as_message(self) -> Message:
        """Convert the documents to a Message."""
        url_contents = self.fetch_url_contents()
        return Message(text="\n\n".join([x["text"] for x in url_contents]), data={"data": url_contents})
