import sys
from pathlib import Path
from update_pyproject_name import update_pyproject_name
from update_pyproject_version import update_version

# Add current dir to sys.path
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir))

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
    update_pyproject_name("pyproject.toml", "openrag-nightly")
    update_version(main_tag)

if __name__ == "__main__":
    main()
