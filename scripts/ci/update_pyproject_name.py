import re
import sys
from pathlib import Path

def update_pyproject_name(file_path: str, new_name: str):
    path = Path(file_path)
    if not path.exists():
        print(f"File {file_path} not found")
        raise SystemExit(1)
    
    content = path.read_text()
    new_content = re.sub(r'^name = "[^"]+"', f'name = "{new_name}"', content, flags=re.M)
    path.write_text(new_content)
    print(f"Updated name in {file_path} to {new_name}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: update_pyproject_name.py <file_path> <new_name>")
        sys.exit(1)
    update_pyproject_name(sys.argv[1], sys.argv[2])
