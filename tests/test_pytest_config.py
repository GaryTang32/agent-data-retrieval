"""The pytest configuration: realdata tests (which read the scratch stores under
`.cache/store-p2` and write table overlays into them) run only when asked for."""

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
REALDATA = "tests/test_tables_realdata.py"


def collect(*args: str) -> str:
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return done.stdout


def test_the_config_deselects_realdata_by_default():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["pytest"]["ini_options"]["addopts"] == "-m 'not realdata'"


def test_realdata_tests_are_not_collected_without_asking():
    out = collect(REALDATA)
    assert "test_tables_realdata.py::" not in out and "deselected" in out


def test_an_explicit_marker_runs_the_realdata_tests():
    out = collect(REALDATA, "-m", "realdata")
    assert "test_tables_realdata.py::test_real_tables_reproduce_the_records" in out
