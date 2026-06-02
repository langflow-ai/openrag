#!/usr/bin/env python3
"""Entrypoint for the OpenRAG Langflow container.

Runs as root to correct /app/data bind-mount permissions, then drops
to uid/gid 1000 (langflow user) before exec-ing the main process.

On macOS with Podman the virtiofs layer does not faithfully propagate
host-side chmod into the container, so permissions must be fixed from
inside the container after the mount is established.
"""

import os
import pathlib
import pwd
import shutil
import sys

# Ensure data directory is writable by the langflow user
data_dir = pathlib.Path("/app/data")
try:
    data_dir.chmod(0o777)
    shutil.chown(data_dir, user=1000, group=1000)
except (OSError, PermissionError):
    pass

# Look up uid 1000's passwd entry so we can restore HOME and USER correctly
# after dropping privileges.  Running as root (USER root in Dockerfile) sets
# HOME=/root; leaving it unchanged causes uv to try /root/.cache/uv, which
# uid 1000 cannot write to.
try:
    pw = pwd.getpwuid(1000)
    home = pw.pw_dir
    user = pw.pw_name
except KeyError:
    home = "/app"
    user = "langflow"

# Create home directory if it doesn't exist and set proper permissions
home_path = pathlib.Path(home)
if not home_path.exists():
    try:
        home_path.mkdir(parents=True, exist_ok=True)
        home_path.chmod(0o755)
        shutil.chown(home, user=1000, group=1000)
    except (OSError, PermissionError):
        pass

# Drop from root to langflow (uid=1000, gid=1000) only when we have the
# privilege to do so. Under OpenShift the container already runs as an
# arbitrary non-root UID, in which case there is nothing to drop.
if os.getuid() == 0:
    os.setgid(1000)
    os.setuid(1000)

# Restore environment variables to reflect the unprivileged user.
os.environ["HOME"] = home
os.environ["USER"] = user

os.execvp(sys.argv[1], sys.argv[1:])
