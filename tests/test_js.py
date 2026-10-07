import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_js_logic():
    files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.mjs"))
    assert len(files) >= 2  # swipe + tabs
    result = subprocess.run(["node", "--test", *files], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
