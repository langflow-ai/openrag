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
import re
import sys

_ROOT_PATH_API_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])(/api/v[12])")
_ROOT_PATH_HEALTH_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])(/health(?:_check)?)")


def normalize_root_path(value: str | None) -> str:
    """Normalize LANGFLOW_ROOT_PATH using Langflow's server-setting rules."""
    normalized = (value or "").strip()
    if not normalized or normalized == "/":
        return ""
    if "://" in normalized or "?" in normalized or "#" in normalized:
        msg = "LANGFLOW_ROOT_PATH must be a path such as /langflow"
        raise ValueError(msg)
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/")


def frontend_roots() -> list[pathlib.Path]:
    """Return the packaged Langflow frontend directories in supported images."""
    roots = [
        pathlib.Path("/app/src/backend/base/langflow/frontend"),
        pathlib.Path("/app/src/backend/langflow/frontend"),
        pathlib.Path("/app/langflow/frontend"),
    ]
    for base in (pathlib.Path("/app/.venv/lib"), pathlib.Path("/usr/local/lib")):
        if not base.exists():
            continue
        roots.extend(base.glob("python*/site-packages/langflow/frontend"))
        roots.extend(base.glob("python*/dist-packages/langflow/frontend"))
    return [root for root in roots if root.is_dir()]


def patch_frontend_base_path(root_path: str, roots: list[pathlib.Path]) -> tuple[int, bool]:
    """Patch root-relative URLs only in Langflow's packaged frontend assets."""
    patched = 0
    already_configured = False
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".css", ".html", ".js", ".mjs"}:
                continue
            original = path.read_text(encoding="utf-8", errors="ignore")
            if (
                f"{root_path}/api/v1" in original
                or f'<base href="{root_path}/"' in original
                or f'basename:"{root_path}"' in original
            ):
                already_configured = True
            updated = _ROOT_PATH_API_PATTERN.sub(
                lambda match: f"{root_path}{match.group(1)}", original
            )
            updated = _ROOT_PATH_HEALTH_PATTERN.sub(
                lambda match: f"{root_path}{match.group(1)}", updated
            )
            updated = updated.replace('<base href="/"', f'<base href="{root_path}/"')
            # Vite minifies `basename: BASENAME || undefined` to this form.
            updated = updated.replace("basename:void 0", f'basename:"{root_path}"')
            if updated == original:
                continue
            path.write_text(updated, encoding="utf-8")
            patched += 1
    return patched, already_configured


def command_with_mounted_base_path(command: list[str]) -> list[str]:
    """Replace Langflow's default CLI command with the image-local wrapper."""
    commands = (
        (["python", "-m", "langflow", "run"], ["python", "/usr/local/bin/langflow-base-path.py"]),
        (
            ["uv", "run", "langflow", "run"],
            ["uv", "run", "python", "/usr/local/bin/langflow-base-path.py"],
        ),
        (["langflow", "run"], ["python", "/usr/local/bin/langflow-base-path.py"]),
    )
    for original, replacement in commands:
        if command[: len(original)] == original:
            return [*replacement, *command[len(original) :]]

    msg = (
        'LANGFLOW_ROOT_PATH requires the Langflow run command. Use "langflow run ...", '
        '"python -m langflow run ...", or "uv run langflow run ...".'
    )
    raise ValueError(msg)


try:
    root_path = normalize_root_path(os.environ.get("LANGFLOW_ROOT_PATH"))
except ValueError as exc:
    sys.stderr.write(f"{exc}\n")
    raise SystemExit(1) from exc

# Langflow's native LANGFLOW_ROOT_PATH setting is for a proxy that strips the
# prefix before forwarding requests.  For direct requests to /<prefix>/..., the
# image-local wrapper strips and mounts the prefix at ASGI level instead.
# Keep the requested prefix separately and leave Langflow's proxy setting off.
os.environ["OPENRAG_LANGFLOW_BASE_PATH"] = root_path
os.environ["LANGFLOW_ROOT_PATH"] = ""
if root_path:
    patched, already_configured = patch_frontend_base_path(root_path, frontend_roots())
    if not patched and not already_configured:
        sys.stderr.write(
            "Unable to apply LANGFLOW_ROOT_PATH: no packaged Langflow frontend assets were found.\n"
        )
        raise SystemExit(1)
    status = "Applied" if patched else "Reused"
    print(f"{status} Langflow base path: '{root_path}'")

try:
    command = sys.argv[1:]
    if root_path:
        command = command_with_mounted_base_path(command)
except ValueError as exc:
    sys.stderr.write(f"{exc}\n")
    raise SystemExit(1) from exc

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
    gid = pw.pw_gid
except KeyError:
    home = "/app"
    user = "langflow"
    gid = 0

# Drop from root to langflow (uid=1000, gid=gid).
os.setgid(gid)
os.setuid(1000)

# Restore environment variables to reflect the unprivileged user.
os.environ["HOME"] = home
os.environ["USER"] = user

# Enable SQLite WAL (Write-Ahead Logging) mode and busy timeout to handle concurrent accesses cleanly.
try:
    import sqlite3

    db_file = data_dir / "langflow.db"
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.close()
except Exception as e:
    sys.stderr.write(f"Warning: could not configure SQLite WAL mode: {e}\n")

os.execvp(command[0], command)
