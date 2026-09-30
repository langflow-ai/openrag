"""Langflow image sitecustomize preloads openai.resources for `langflow run` (#2436)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/langflow_sitecustomize.py")


def _load():
    spec = importlib.util.spec_from_file_location("langflow_sitecustomize", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-m", "langflow", "run", "--host", "0.0.0.0", "--port", "7860"],
        ["/app/.venv/bin/python", "/app/.venv/bin/langflow", "run", "--env-file", "/app/.env"],
        ["uv", "run", "langflow", "run", "--host", "0.0.0.0"],
    ],
)
def test_detects_langflow_server(argv):
    assert _load().is_langflow_server(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-m", "langflow", "--version"],
        ["python", "/tmp/patch_langflow_openrag_bundle.py"],
        ["python", "-c", "print('hi')"],
        ["python", "-m", "langflow"],
        ["uv", "run", "python", "script.py"],
    ],
)
def test_ignores_other_processes(argv):
    assert not _load().is_langflow_server(argv)


def test_preload_failure_does_not_raise(monkeypatch, capsys):
    module = _load()
    monkeypatch.setitem(sys.modules, "openai.resources", None)  # makes the import fail

    module.preload_openai_resources()

    assert "could not preload openai.resources" in capsys.readouterr().err


def test_preload_prevents_concurrent_lazy_import_deadlock(tmp_path):
    """Three threads touching different lazy openai client resources at once
    deadlock on a cold interpreter; after the preload they don't."""
    pytest.importorskip("openai")
    race = tmp_path / "race.py"
    race.write_text(
        "import importlib.util, sys, threading\n"
        f"spec = importlib.util.spec_from_file_location('sc', {str(SCRIPT.resolve())!r})\n"
        "sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)\n"
        "import openai\n"
        "sc.preload_openai_resources()\n"
        "barrier = threading.Barrier(3)\n"
        "errors = []\n"
        "def touch(attr):\n"
        "    barrier.wait()\n"
        "    try:\n"
        "        getattr(openai.OpenAI(api_key='x'), attr)\n"
        "    except Exception as exc:\n"
        "        errors.append(type(exc).__name__)\n"
        "threads = [threading.Thread(target=touch, args=(a,)) for a in ('embeddings', 'chat', 'beta')]\n"
        "[t.start() for t in threads]; [t.join() for t in threads]\n"
        "print(','.join(errors) or 'ok')\n"
    )

    for _ in range(5):
        result = subprocess.run(
            [sys.executable, str(race)], capture_output=True, text=True, timeout=60
        )
        assert result.stdout.strip() == "ok", result.stdout + result.stderr
