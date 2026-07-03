#!/usr/bin/env python3
import glob
import hashlib
import os
import sys


def get_hash(paths):
    hasher = hashlib.sha256()

    # Track files to hash to ensure deterministic sorting
    files_to_hash = []

    for path in paths:
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for f in files:
                    full_path = os.path.join(root, f)
                    files_to_hash.append(full_path)
        elif "*" in path or "?" in path:
            # Handle glob patterns
            for matched in glob.glob(path, recursive=True):
                if os.path.isdir(matched):
                    for root, _, files in os.walk(matched):
                        for f in files:
                            files_to_hash.append(os.path.join(root, f))
                else:
                    files_to_hash.append(matched)
        elif os.path.exists(path):
            files_to_hash.append(path)

    # Sort files deterministically and hash them
    for fp in sorted(set(files_to_hash)):
        # We only hash standard files
        if os.path.isfile(fp):
            # Ignore files that might be unreadable (e.g. root-owned leftovers)
            try:
                # Include filename in hash to distinguish different file structures
                hasher.update(os.path.relpath(fp).encode("utf-8"))
                hasher.update(b"\0")
                with open(fp, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
                hasher.update(b"\0")
            except (PermissionError, FileNotFoundError):
                continue

    return hasher.hexdigest()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: get_image_hash.py <file_or_dir1> [file_or_dir2 ...]")
        sys.exit(1)

    print(get_hash(sys.argv[1:]))
