import sys
import requests
from packaging.version import Version
from pathlib import Path
import tomllib
from typing import Optional

PYPI_OPENRAG_NIGHTLY_URL = "https://pypi.org/pypi/openrag-nightly/json"
PYPI_OPENRAG_URL = "https://pypi.org/pypi/openrag/json"

def get_latest_published_version(is_nightly: bool) -> Optional[Version]:
    url = PYPI_OPENRAG_NIGHTLY_URL if is_nightly else PYPI_OPENRAG_URL
    res = requests.get(url, timeout=10)
    if res.status_code == 404:
        return None
    res.raise_for_status()
    try:
        version_str = res.json()["info"]["version"]
    except Exception as e:
        msg = "Got unexpected response from PyPI"
        raise RuntimeError(msg) from e
    return Version(version_str)

def create_tag():
    # Read version from pyproject.toml
    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    current_version_str = pyproject_data["project"]["version"]
    current_version = Version(current_version_str)

    try:
        current_nightly_version = get_latest_published_version(is_nightly=True)
    except (requests.RequestException, KeyError, ValueError):
        current_nightly_version = None

    build_number = "0"
    latest_base_version = current_version.base_version
    nightly_base_version = current_nightly_version.base_version if current_nightly_version else None

    if latest_base_version == nightly_base_version:
        dev_number = (current_nightly_version.dev if current_nightly_version.dev is not None else -1) if current_nightly_version else -1
        build_number = str(dev_number + 1)

    # Build PEP 440-compliant nightly version (without leading "v")
    nightly_version_str = f"{latest_base_version}.dev{build_number}"

    # Verify PEP440
    Version(nightly_version_str)

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
