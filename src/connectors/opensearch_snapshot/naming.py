"""Opaque, OpenRAG-owned names for restored snapshot datasets.

Physical names never contain source index names. ``assert_outside_user_patterns``
guarantees a generated name cannot match any index pattern that an existing
OpenRAG user role already grants, so a dataset can never be reached through
another role's grant.
"""

from __future__ import annotations

import fnmatch
import re
import secrets
import string
from functools import lru_cache
from pathlib import Path

import yaml

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]{9}$")
_SLUG_FIRST = string.ascii_lowercase
_SLUG_REST = string.ascii_lowercase + string.digits
_DATASET_ROLE_PREFIX = "openrag_ds_"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROLE_FILES = (
    "securityconfig/roles.yml",
    "cloud_securityconfig/roles.yml",
)


class NamingError(ValueError):
    """A generated name is invalid or collides with an existing role grant."""


def new_slug() -> str:
    """Random import slug: 10 chars, ``[a-z][a-z0-9]{9}``."""
    return secrets.choice(_SLUG_FIRST) + "".join(secrets.choice(_SLUG_REST) for _ in range(9))


def is_valid_slug(slug: str) -> bool:
    return isinstance(slug, str) and _SLUG_RE.fullmatch(slug) is not None


def _require_slug(slug: str) -> str:
    if not is_valid_slug(slug):
        raise NamingError("invalid import slug")
    return slug


def _require_ordinal(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise NamingError(f"invalid {label}")
    return value


def alias_name(slug: str, ordinal: int) -> str:
    """Stable alias serving dataset ``ordinal`` of an import: ``ds_{slug}_{n}``."""
    return f"ds_{_require_slug(slug)}_{_require_ordinal(ordinal, 'ordinal')}"


def concrete_name(slug: str, ordinal: int, generation: int) -> str:
    """Generation-specific restored index: ``ds_{slug}_{n}_g{gen}``."""
    return f"{alias_name(slug, ordinal)}_g{_require_ordinal(generation, 'generation')}"


def slug_pattern(slug: str) -> str:
    """Index pattern covering every alias and concrete index of one import."""
    return f"ds_{_require_slug(slug)}_*"


def role_name(slug: str) -> str:
    return f"{_DATASET_ROLE_PREFIX}{_require_slug(slug)}"


def repo_name(slug: str, generation: int) -> str:
    """OpenSearch snapshot repository registered over one staged generation."""
    return f"openrag_stage_{_require_slug(slug)}_g{_require_ordinal(generation, 'generation')}"


def _load_patterns(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}
    patterns: list[str] = []
    for role_id, role in doc.items():
        if role_id.startswith("_") or not isinstance(role, dict):
            continue
        if role_id.startswith(_DATASET_ROLE_PREFIX):
            continue
        for perm in role.get("index_permissions") or []:
            for pattern in perm.get("index_patterns") or []:
                patterns.append(str(pattern))
    return patterns


@lru_cache(maxsize=1)
def _user_patterns() -> tuple[str, ...]:
    found: list[str] = []
    seen_file = False
    for rel in _ROLE_FILES:
        path = _REPO_ROOT / rel
        if not path.is_file():
            continue
        seen_file = True
        found.extend(_load_patterns(path))
    if not seen_file:
        # Fail closed: without the role definitions we cannot prove isolation.
        raise NamingError("security role definitions are unavailable")
    return tuple(dict.fromkeys(found))


def _pattern_matches(pattern: str, name: str) -> bool:
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        try:
            return re.fullmatch(pattern[1:-1], name) is not None
        except re.error:
            return True  # unparseable pattern: assume it could match
    return fnmatch.fnmatchcase(name, pattern)


def assert_outside_user_patterns(name: str) -> None:
    """Reject ``name`` when any non-dataset role pattern would match it.

    Reads the ``index_patterns`` of every role in ``securityconfig/roles.yml``
    and ``cloud_securityconfig/roles.yml`` except ``openrag_ds_*`` roles.
    """
    for pattern in _user_patterns():
        if _pattern_matches(pattern, name):
            raise NamingError("generated index name collides with an existing role pattern")
