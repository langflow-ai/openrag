"""Filesystem identity checks for rotation and promotion."""

from pathlib import Path


def overlaps(first: Path, second: Path) -> bool:
    if first.is_relative_to(second) or second.is_relative_to(first):
        return True
    return (
        first.exists()
        and any(first.samefile(path) for path in (second, *second.parents) if path.exists())
    ) or (second.exists() and any(second.samefile(path) for path in first.parents if path.exists()))
