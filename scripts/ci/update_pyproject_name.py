import re
import sys
from pathlib import Path

def update_pyproject_name(new_name: str):
    path = Path("pyproject.toml")
    if not path.exists():
        print("File pyproject.toml not found")
        raise SystemExit(1)
    
    content = path.read_text()
    new_content = re.sub(r'^name = "[^"]+"', f'name = "{new_name}"', content, flags=re.M)
    
    # Fail if the name pattern was not found / no substitution was made
    if new_content == content:
        print(
            'Error: Could not find a line matching `name = "..."` in pyproject.toml to update.',
            file=sys.stderr,
        )
        sys.exit(1)
        
    path.write_text(new_content)
    print(f"Updated name in pyproject.toml to {new_name}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: update_pyproject_name.py <new_name>")
        sys.exit(1)
    update_pyproject_name(sys.argv[1])
