#!/usr/bin/env python3
"""Entrypoint for the OpenRAG Langflow container.

Started as root (docker-compose default, k8s pods without a securityContext):
fixes ownership of the data directories (uid 1000, gid 0) when needed, then
drops to uid 1000 before exec-ing the main process.

Started as a non-root user (Helm runAsUser 1000, OpenShift arbitrary UIDs,
custom runAsUser values): skips all privilege operations and execs directly.
Volume writability then comes from fsGroup or the image's group-0 g+rwX
permissions.

On macOS with Podman the virtiofs layer does not faithfully propagate
host-side chmod into the container, so the mount-point permissions are fixed
from inside the container after the mount is established.
"""

import os
import pathlib
import pwd
import stat
import sys

TARGET_UID = 1000
TARGET_GID = 0

# /app/data is the Kubernetes (Helm/operator) mount point; /app/langflow-data
# is the docker-compose mount point. Handle both so the image works unchanged
# in every environment.
DATA_DIRS = [pathlib.Path("/app/data"), pathlib.Path("/app/langflow-data")]


def chmod_mount_point(d: pathlib.Path) -> None:
    """macOS Podman virtiofs workaround: fix the top-level mount permissions."""
    try:
        d.chmod(0o777)
    except OSError:
        pass


def fix_tree(d: pathlib.Path) -> None:
    """Recursively chown/chmod a data dir to uid 1000, gid 0 with g+rwX.

    Walks bottom-up and chowns the top-level dir last so its ownership doubles
    as a "fix completed" marker — an interrupted run is retried on the next
    boot, and a correctly-owned dir skips the walk entirely (same semantics as
    k8s fsGroupChangePolicy: OnRootMismatch).
    """
    for root, dirs, files in os.walk(d, topdown=False):
        for name in files + dirs:
            p = os.path.join(root, name)
            try:
                os.lchown(p, TARGET_UID, TARGET_GID)
                st = os.lstat(p)
                if not stat.S_ISLNK(st.st_mode):
                    extra = 0o770 if stat.S_ISDIR(st.st_mode) else 0o660
                    os.chmod(p, st.st_mode | extra)
            except OSError:
                pass
    os.chown(d, TARGET_UID, TARGET_GID)
    os.chmod(d, os.stat(d).st_mode | 0o770)


if os.getuid() == 0:
    for data_dir in DATA_DIRS:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        chmod_mount_point(data_dir)
        st = data_dir.stat()
        if st.st_uid != TARGET_UID or st.st_gid != TARGET_GID:
            try:
                fix_tree(data_dir)
            except OSError:
                pass

    # Drop from root to uid 1000 / gid 0. Tolerate failure (e.g. a runtime
    # that strips CAP_SETUID/CAP_SETGID while keeping uid 0) with a loud
    # warning instead of crash-looping the container.
    try:
        os.setgroups([TARGET_GID])
    except OSError:
        pass
    try:
        os.setgid(TARGET_GID)
        os.setuid(TARGET_UID)
    except OSError as exc:
        print(
            f"langflow-entrypoint: WARNING: could not drop privileges: {exc}",
            file=sys.stderr,
        )

    # Restore HOME/USER for the unprivileged user, but only when the runtime
    # left root's values behind — deployments that set HOME explicitly
    # (e.g. Helm sets HOME=/app/data) must keep their value.
    if os.environ.get("HOME") in (None, "", "/root", "/"):
        try:
            pw = pwd.getpwuid(os.getuid())
            os.environ["HOME"] = pw.pw_dir
            os.environ.setdefault("USER", pw.pw_name)
        except KeyError:
            os.environ["HOME"] = "/tmp"
    os.environ.setdefault("USER", "langflow")
else:
    # Non-root start: setuid/setgid would raise EPERM, and chown is not
    # possible. Only attempt the virtiofs mount-point fix and rely on
    # fsGroup / group-0 permissions for writability.
    for data_dir in DATA_DIRS:
        chmod_mount_point(data_dir)
    if os.environ.get("HOME") in (None, "", "/root", "/"):
        os.environ["HOME"] = "/tmp"

if len(sys.argv) < 2:
    sys.exit("langflow-entrypoint: no command given")

os.execvp(sys.argv[1], sys.argv[1:])
