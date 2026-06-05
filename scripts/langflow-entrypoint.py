#!/usr/bin/env python3
"""Entrypoint for the OpenRAG Langflow container.

Prepare the Langflow data directory, then drop to uid/gid 1000 when the
container starts as root.
"""

import os
import pathlib
import pwd
import shutil
import sys

TARGET_UID = 1000
TARGET_GID = 1000

data_dir = pathlib.Path(
    os.environ.get("APP_DATA_DIR")
    or os.environ.get("LANGFLOW_CONFIG_DIR")
    or os.environ.get("HOME")
    or "/app/data"
)

for path in (data_dir, data_dir / ".cache", data_dir / ".mem0", data_dir / ".gunicorn"):
    try:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(path.stat().st_mode | 0o770)
    except OSError:
        pass

if os.geteuid() == 0:
    for path in (data_dir, *data_dir.iterdir()):
        try:
            shutil.chown(path, user=TARGET_UID, group=TARGET_GID)
            path.chmod(path.stat().st_mode | (0o770 if path.is_dir() else 0o660))
        except OSError:
            pass

    try:
        user = pwd.getpwuid(TARGET_UID).pw_name
        os.setgid(TARGET_GID)
        os.setuid(TARGET_UID)
        os.environ["USER"] = user
    except OSError as exc:
        print(f"Failed to drop privileges to uid {TARGET_UID}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

os.environ["HOME"] = str(data_dir)
os.environ["XDG_CACHE_HOME"] = os.environ.get("XDG_CACHE_HOME", str(data_dir / ".cache"))
os.environ["MEM0_DIR"] = os.environ.get("MEM0_DIR", str(data_dir / ".mem0"))
os.environ["LANGFLOW_CONFIG_DIR"] = os.environ.get("LANGFLOW_CONFIG_DIR", str(data_dir))
os.environ["GUNICORN_CMD_ARGS"] = os.environ.get(
    "GUNICORN_CMD_ARGS",
    f"--worker-tmp-dir {data_dir / '.gunicorn'}",
)

os.execvp(sys.argv[1], sys.argv[1:])
