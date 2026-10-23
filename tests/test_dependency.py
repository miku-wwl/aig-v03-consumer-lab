from __future__ import annotations

import json
import sys
from importlib.metadata import distribution, version
from pathlib import Path

import agentic_intent_gate.runtime as runtime

EXPECTED_COMMIT = "bb8e8fb1234128613a750bee17967b225072bb14"


def test_installed_release_and_immutable_source_identity():
    assert version("agentic-intent-gate") == "0.3.0"
    direct_url = json.loads(distribution("agentic-intent-gate").read_text("direct_url.json"))
    assert direct_url["vcs_info"]["vcs"] == "git"
    assert direct_url["vcs_info"]["commit_id"] == EXPECTED_COMMIT
    assert direct_url["vcs_info"]["requested_revision"] == EXPECTED_COMMIT
    runtime_path = Path(runtime.__file__).resolve()
    assert runtime_path.is_relative_to(Path(sys.prefix).resolve())


def test_project_manifest_uses_only_immutable_release_commit():
    manifest = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    lock = (Path(__file__).resolve().parents[1] / "uv.lock").read_text("utf-8")
    assert f"agentic-intent-gate.git@{EXPECTED_COMMIT}" in manifest
    assert EXPECTED_COMMIT in lock
    assert (
        "https://github.com/miku-wwl/agentic-intent-gate.git?rev="
        + EXPECTED_COMMIT
        + "#"
        + EXPECTED_COMMIT
    ) in lock
