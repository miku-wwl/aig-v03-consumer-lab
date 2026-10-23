#!/usr/bin/env python3
"""Fetch and reproducibly compose the upstream AIG consumer instructions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = (
    "https://raw.githubusercontent.com/miku-wwl/agentic-intent-gate/main/docs/AGENTS-dependence.md"
)
API_ROOT = "https://api.github.com/repos/miku-wwl/agentic-intent-gate"
EXPECTED_RELEASE = "v0.3.0"
EXPECTED_COMMIT = "bb8e8fb1234128613a750bee17967b225072bb14"
MAX_SOURCE_BYTES = 256 * 1024
MAX_API_BYTES = 512 * 1024
TIMEOUT_SECONDS = 15
SOURCE_PATH = Path("docs/upstream/AGENTS-dependence.md")
OVERLAY_PATH = Path("config/agents-overlay.md")
GENERATED_PATH = Path("AGENTS.md")
PROVENANCE_PATH = Path("docs/AGENTS-PROVENANCE.json")


class SyncError(RuntimeError):
    """Raised when the source cannot be safely synchronized."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _request(url: str, *, limit: int, accept: str) -> bytes:
    request = Request(
        url,
        headers={"Accept": accept, "User-Agent": "aig-v03-consumer-lab-agents-sync/1"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise SyncError(f"HTTP status {response.status} for {url}")
            expected_url = urlsplit(url)
            actual_url = urlsplit(response.geturl())
            if (
                expected_url.scheme != "https"
                or actual_url.scheme != "https"
                or actual_url.hostname != expected_url.hostname
                or actual_url.port not in (None, 443)
                or actual_url.username is not None
            ):
                raise SyncError(f"Unexpected redirect destination for {url}")
            data = response.read(limit + 1)
    except HTTPError as exc:
        raise SyncError(f"HTTP status {exc.code} for {url}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SyncError(f"HTTPS request failed for {url}: {exc}") from exc
    if len(data) > limit:
        raise SyncError(f"Response exceeds {limit} bytes: {url}")
    return data


def fetch_source() -> tuple[bytes, str, str]:
    """Fetch raw main and bind it to the verified GitHub main commit/blob."""
    raw = _request(SOURCE_URL, limit=MAX_SOURCE_BYTES, accept="text/plain")
    if not raw or not raw.strip():
        raise SyncError("Upstream instruction document is empty")
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SyncError("Upstream instruction document is not valid UTF-8") from exc

    ref = get_json(f"{API_ROOT}/git/ref/heads/main")
    commit_sha = _required_sha(ref.get("object", {}).get("sha"), "main commit")
    contents_url = f"{API_ROOT}/contents/docs/AGENTS-dependence.md?{urlencode({'ref': commit_sha})}"
    contents = get_json(contents_url)
    blob_sha = _required_sha(contents.get("sha"), "source blob")
    if git_blob_sha(raw) != blob_sha:
        raise SyncError("Raw main document does not match the GitHub main snapshot")
    return raw, commit_sha, blob_sha


def get_json(url: str) -> dict[str, Any]:
    raw = _request(url, limit=MAX_API_BYTES, accept="application/vnd.github+json")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"Invalid GitHub API JSON from {url}") from exc
    if not isinstance(result, dict):
        raise SyncError(f"Unexpected GitHub API response from {url}")
    return result


def _required_sha(value: object, description: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise SyncError(f"GitHub returned an invalid {description} SHA")
    return value


def verify_release_tag(api_get=get_json) -> None:
    """Require the published annotated v0.3.0 tag to peel to the fixed commit."""
    ref = api_get(f"{API_ROOT}/git/ref/tags/{EXPECTED_RELEASE}")
    tag_ref = ref.get("object", {})
    if tag_ref.get("type") != "tag":
        raise SyncError("v0.3.0 must remain an annotated Git tag")
    tag_sha = _required_sha(tag_ref.get("sha"), "annotated tag object")
    tag = api_get(f"{API_ROOT}/git/tags/{tag_sha}")
    target = tag.get("object", {})
    if target.get("type") != "commit" or target.get("sha") != EXPECTED_COMMIT:
        raise SyncError("Annotated v0.3.0 tag does not peel to the required immutable commit")


def validate_source(raw: bytes) -> str:
    if len(raw) > MAX_SOURCE_BYTES or not raw.strip():
        raise SyncError("Upstream instruction document is empty or oversized")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SyncError("Upstream instruction document is not valid UTF-8") from exc
    required = (
        "Agentic Intent Gate",
        "v0.3.0",
        EXPECTED_COMMIT,
        "agentic_intent_gate.runtime",
        "Approval",
        "Authorization",
        "durable Action",
        "Unknown",
        "Do not copy, fork, reimplement, monkeypatch, or bypass",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise SyncError(
            "Upstream document is missing required AIG safety identity: " + ", ".join(missing)
        )
    dependency_line = (
        "agentic-intent-gate @ git+https://github.com/miku-wwl/agentic-intent-gate.git@"
        + EXPECTED_COMMIT
    )
    if dependency_line not in text:
        raise SyncError("Upstream document does not pin the expected immutable AIG commit")
    return text


def generated_agents(source: bytes, overlay: bytes) -> bytes:
    validate_source(source)
    if not overlay.strip():
        raise SyncError("Consumer overlay is empty")
    try:
        overlay.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SyncError("Consumer overlay is not valid UTF-8") from exc
    separator = b"\n" if source.endswith(b"\n") else b"\n\n"
    return source + separator + overlay


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def refresh(root: Path = ROOT) -> dict[str, str]:
    raw, source_commit, blob_sha = fetch_source()
    validate_source(raw)
    verify_release_tag()
    overlay_path = root / OVERLAY_PATH
    try:
        overlay = overlay_path.read_bytes()
    except OSError as exc:
        raise SyncError(f"Cannot read consumer overlay {overlay_path}: {exc}") from exc
    root_agents = generated_agents(raw, overlay)
    provenance = {
        "schema_version": 1,
        "source_url": SOURCE_URL,
        "source_commit": source_commit,
        "source_blob_sha": blob_sha,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "content_sha256": sha256(raw),
        "expected_aig_release": EXPECTED_RELEASE,
        "expected_release_commit": EXPECTED_COMMIT,
        "generated_agents_sha256": sha256(root_agents),
        "overlay_sha256": sha256(overlay),
    }
    _atomic_write(root / SOURCE_PATH, raw)
    _atomic_write(root / GENERATED_PATH, root_agents)
    _atomic_write(
        root / PROVENANCE_PATH,
        (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return provenance


def check(root: Path = ROOT) -> dict[str, str]:
    try:
        source = (root / SOURCE_PATH).read_bytes()
        overlay = (root / OVERLAY_PATH).read_bytes()
        generated = (root / GENERATED_PATH).read_bytes()
        provenance = json.loads((root / PROVENANCE_PATH).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(
            f"Committed synchronization snapshot is incomplete or invalid: {exc}"
        ) from exc
    validate_source(source)
    expected_generated = generated_agents(source, overlay)
    if provenance.get("schema_version") != 1:
        raise SyncError("Unsupported AGENTS provenance schema")
    exact = {
        "source_url": SOURCE_URL,
        "content_sha256": sha256(source),
        "expected_aig_release": EXPECTED_RELEASE,
        "expected_release_commit": EXPECTED_COMMIT,
        "generated_agents_sha256": sha256(expected_generated),
        "overlay_sha256": sha256(overlay),
    }
    for key, value in exact.items():
        if provenance.get(key) != value:
            raise SyncError(f"AGENTS provenance mismatch: {key}")
    _required_sha(provenance.get("source_commit"), "recorded source commit")
    recorded_blob = _required_sha(provenance.get("source_blob_sha"), "recorded source blob")
    retrieved_at = provenance.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise SyncError("AGENTS provenance retrieval timestamp is missing")
    if not retrieved_at.endswith("Z"):
        raise SyncError("AGENTS provenance retrieval timestamp must be UTC")
    try:
        datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SyncError("AGENTS provenance retrieval timestamp is invalid") from exc
    if git_blob_sha(source) != recorded_blob:
        raise SyncError("Recorded GitHub blob identity does not match saved upstream document")
    if generated != expected_generated:
        raise SyncError("Generated AGENTS.md differs from the saved upstream source and overlay")
    return {
        "source_sha256": sha256(source),
        "generated_sha256": sha256(generated),
        "status": "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--refresh", action="store_true", help="fetch verified upstream main and regenerate files"
    )
    action.add_argument(
        "--check", action="store_true", help="verify the committed snapshot without network access"
    )
    args = parser.parse_args(argv)
    try:
        result = refresh() if args.refresh else check()
    except SyncError as exc:
        print(f"AGENTS_SYNC=FAIL: {exc}", file=sys.stderr)
        return 1
    print("AGENTS_SYNC=PASS")
    print(f"SOURCE_SHA256={result.get('content_sha256', result.get('source_sha256'))}")
    generated_hash = result.get("generated_agents_sha256", result.get("generated_sha256"))
    print(f"GENERATED_AGENTS_SHA256={generated_hash}")
    if args.refresh:
        print(f"SOURCE_COMMIT={result['source_commit']}")
        print(f"SOURCE_BLOB_SHA={result['source_blob_sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
