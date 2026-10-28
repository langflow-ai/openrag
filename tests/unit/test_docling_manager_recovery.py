"""The TUI reconnects to a docling-serve left running by an earlier session."""

import os
import subprocess
import sys
import time

import pytest

from tui.managers import docling_manager as dm


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@pytest.fixture
def tui_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.paths.get_tui_dir", lambda: tmp_path)
    monkeypatch.setattr(dm.DoclingManager, "_instance", None)
    return tmp_path


def _spawn_detached(command: str) -> int:
    """Start `command` detached. It's not our child, so it doesn't linger as a
    zombie once killed."""
    out = subprocess.run(
        ["sh", "-c", f"{command} >/dev/null 2>&1 & echo $!"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip())


@pytest.fixture
def running_server():
    """A process standing in for docling-serve: its command line names it."""
    pid = _spawn_detached(f"{sys.executable} -c 'import time; time.sleep(60)' docling-serve run")
    yield pid
    if _alive(pid):
        os.kill(pid, 9)


@pytest.fixture
def unrelated_process():
    pid = _spawn_detached("sleep 60")
    yield pid
    if _alive(pid):
        os.kill(pid, 9)


def _wait_gone(pid: int, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_keeps_a_server_launched_with_current_settings(tui_dir, running_server):
    (tui_dir / ".docling.pid").write_text(str(running_server))
    (tui_dir / ".docling.launch").write_text(dm.DOCLING_LAUNCH_VERSION)

    manager = dm.DoclingManager()

    assert manager.is_running()
    assert _alive(running_server)


def test_stops_a_server_launched_by_an_older_tui(tui_dir, running_server):
    """An older TUI launched docling-serve without custom OCR config allowed, so
    every ingest with the easyocr threshold would fail against it."""
    (tui_dir / ".docling.pid").write_text(str(running_server))

    manager = dm.DoclingManager()

    assert _wait_gone(running_server)
    assert not manager.is_running()
    assert not (tui_dir / ".docling.pid").exists()


def test_leaves_alone_an_unrelated_process_that_reused_the_pid(tui_dir, unrelated_process):
    """docling-serve died and the OS gave its PID to something else."""
    (tui_dir / ".docling.pid").write_text(str(unrelated_process))

    manager = dm.DoclingManager()

    assert _alive(unrelated_process)
    assert not manager.is_running()
    assert not (tui_dir / ".docling.pid").exists()


def test_launch_marker_follows_the_pid_file(tui_dir):
    manager = dm.DoclingManager()

    manager._save_pid(12345)
    assert (tui_dir / ".docling.launch").read_text() == dm.DOCLING_LAUNCH_VERSION

    manager._clear_pid_file()
    assert not (tui_dir / ".docling.launch").exists()
