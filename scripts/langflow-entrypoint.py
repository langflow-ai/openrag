#!/usr/bin/env python3
"""Entrypoint for the OpenRAG Langflow container.

Runs as root to correct /app/langflow-data bind-mount permissions, then drops
to uid/gid 1000 (langflow user) before exec-ing the main process.

On macOS with Podman the virtiofs layer does not faithfully propagate
host-side chmod into the container, so permissions must be fixed from
inside the container after the mount is established.
"""
import os
import pathlib
import pwd
import sys

data_dir = pathlib.Path("/app/langflow-data")

try:
    data_dir.chmod(0o777)
except OSError:
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

# Drop from root to langflow (uid=1000, gid=1000).
os.setgid(1000)
os.setuid(1000)

# Restore environment variables to reflect the unprivileged user.
os.environ["HOME"] = home
os.environ["USER"] = user

os.execvp(sys.argv[1], sys.argv[1:])
