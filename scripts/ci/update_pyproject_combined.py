import sys
from pathlib import Path

# Add current dir to sys.path
current_dir = Path(__file__).resolve().parent
current_dir_str = str(current_dir)
if current_dir_str not in sys.path:
    sys.path.append(current_dir_str)

from update_pyproject_name import update_pyproject_name
from update_pyproject_version import update_version

def main():
    if len(sys.argv) != 3:
        print("Usage: update_pyproject_combined.py main <main_tag>")
        sys.exit(1)
    
    mode = sys.argv[1]
    main_tag = sys.argv[2]
    
    if mode != "main":
        print("Only 'main' mode is supported")
        sys.exit(1)
    
    # Update name and version for openrag
    update_pyproject_name("openrag-nightly")
    update_version(main_tag)

if __name__ == "__main__":
    main()
