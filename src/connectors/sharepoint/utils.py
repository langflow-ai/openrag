from urllib.parse import urlparse


def is_valid_sharepoint_url(url: str) -> bool:
    """
    Validate that a URL belongs to a SharePoint domain.

    Performs proper hostname validation to prevent URL substring
    sanitization attacks. Only accepts URLs where the hostname
    ends with .sharepoint.com.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname

        # Ensure we have a valid hostname
        if not hostname:
            return False

        # Convert to lowercase for case-insensitive comparison
        hostname = hostname.lower()

        # Validate that hostname ends with .sharepoint.com
        # This prevents attacks like: evil.sharepoint.com.attacker.com
        # Also ensure it's not just ".sharepoint.com" (no bare suffix)
        return hostname.endswith(".sharepoint.com") and len(hostname) > len(
            ".sharepoint.com"
        )
    except (ValueError, AttributeError):
        # Invalid URL or parsing error
        return False

