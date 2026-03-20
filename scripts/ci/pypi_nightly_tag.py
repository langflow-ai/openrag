import sys
import requests
from packaging.version import Version, InvalidVersion
from pathlib import Path
import tomllib
from typing import Optional

PYPI_OPENRAG_NIGHTLY_URL = "https://pypi.org/pypi/openrag-nightly/json"
PYPI_OPENRAG_URL = "https://pypi.org/pypi/openrag/json"

def get_latest_published_version(project_name: str) -> Optional[Version]:
    url = f"https://pypi.org/pypi/{project_name}/json"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 404:
            return None
        res.raise_for_status()
        data = res.json()
        all_versions = [Version(v) for v in data.get("releases", {}).keys()]
        if not all_versions:
            return None
        return max(all_versions)
    except (requests.RequestException, KeyError, ValueError, InvalidVersion):
        return None

def create_tag():
    # Read version from pyproject.toml
    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    local_version_str = pyproject_data["project"]["version"]
    local_version = Version(local_version_str)

    # Check both projects on PyPI
    pypi_main = get_latest_published_version("openrag")
    pypi_nightly = get_latest_published_version("openrag-nightly")

    # Find the absolute latest version between local and both pypi versions
    # We use this as a reference point for the dev suffix
    versions_to_check = [v for v in [local_version, pypi_main, pypi_nightly] if v is not None]
    latest_known_version = max(versions_to_check)

    build_number = 0
    base_version = local_version.base_version

    # If the latest version on PyPI matches our local base version (or is higher),
    # we need to increment the dev suffix.
    if latest_known_version.base_version == base_version:
        if latest_known_version.dev is not None:
            build_number = latest_known_version.dev + 1
        else:
            # If the latest is a stable release (no dev suffix), we still need to
            # increment because you shouldn't have dev releases for an already released version
            # However, PEP 440 doesn't strictly forbid 0.3.2.dev0 if 0.3.2 already exists,
            # but usually you'd move to the next minor/patch.
            # For now, let's keep the dev0 for the next version if possible?
            # Actually, standard practice for nightlies if base version is out: move to next patch.
            # But we respect the version in pyproject.toml.
            build_number = 0

    # Build PEP 440-compliant nightly version (without leading "v")
    nightly_version_str = f"{base_version}.dev{build_number}"

    # Git tag uses a leading "v" prefix
    new_nightly_version = f"v{nightly_version_str}"
    return new_nightly_version

if __name__ == "__main__":
    try:
        tag = create_tag()
        print(tag)
    except Exception as e:
        print(f"Error creating tag: {e}", file=sys.stderr)
        sys.exit(1)
