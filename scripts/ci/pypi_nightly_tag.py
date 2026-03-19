import sys
import requests
from packaging.version import Version, InvalidVersion
from pathlib import Path
import tomllib
from typing import Optional

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

    # Check PyPI for the latest published stable version
    pypi_main = get_latest_published_version("openrag")

    # Find the highest version between local and PyPI
    # We use this as a reference point for the dev suffix
    versions_to_check = [v for v in [local_version, pypi_main] if v is not None]
    latest_known_version = max(versions_to_check)

    build_number = 1  # dev builds start at .dev1
    base_version = local_version.base_version

    # If the latest known version shares the same base, increment from its dev suffix
    if latest_known_version.base_version == base_version:
        if latest_known_version.dev is not None:
            build_number = latest_known_version.dev + 1

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
