import re
import sys
from pathlib import Path
from packaging.version import Version, InvalidVersion

def update_version(new_version):
    pyproject_path = Path("pyproject.toml")
    with open(pyproject_path, "r") as f:
        content = f.read()

    # Update the version field
    # Removes 'v' prefix if present from tag
    clean_version = new_version.lstrip('v')

    # Validate that the resulting version is a valid PEP 440 version
    try:
        Version(clean_version)
    except InvalidVersion:
        print(
            f"Error: '{clean_version}' is not a valid PEP 440 version after stripping any leading 'v'.",
            file=sys.stderr,
        )
        sys.exit(1)

    new_content = re.sub(
        r'^version = "[^"]+"',
        f'version = "{clean_version}"',
        content,
        flags=re.M,
    )

    # Fail if the version pattern was not found / no substitution was made
    if new_content == content:
        print(
            'Error: Could not find a line matching `version = "..."` in pyproject.toml to update.',
            file=sys.stderr,
        )
        sys.exit(1)

    with open(pyproject_path, "w") as f:
        f.write(new_content)
    print(f"Updated pyproject.toml version to {clean_version}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python update_pyproject_version.py <new_version>")
        sys.exit(1)
    update_version(sys.argv[1])
