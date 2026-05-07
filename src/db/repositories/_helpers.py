import hashlib


def email_lookup_hash(email: str) -> str:
    """SHA-256 of lowercased email — used as the unique deterministic lookup key
    even though the email column itself is non-deterministically encrypted."""
    if not email:
        return ""
    return hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()
