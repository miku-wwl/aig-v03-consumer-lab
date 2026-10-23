from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sync_agents = import_module("sync_agents")

SOURCE = (ROOT / sync_agents.SOURCE_PATH).read_bytes()
OVERLAY = (ROOT / sync_agents.OVERLAY_PATH).read_bytes()


def test_real_downloaded_snapshot_and_generated_agents_pass_check():
    result = sync_agents.check(ROOT)
    assert result["status"] == "PASS"
    assert (
        sync_agents.git_blob_sha(SOURCE)
        == json.loads((ROOT / sync_agents.PROVENANCE_PATH).read_text("utf-8"))["source_blob_sha"]
    )


def test_successful_refresh_download_and_transformation(tmp_path, monkeypatch):
    (tmp_path / sync_agents.OVERLAY_PATH).parent.mkdir(parents=True)
    (tmp_path / sync_agents.OVERLAY_PATH).write_bytes(OVERLAY)
    monkeypatch.setattr(
        sync_agents,
        "fetch_source",
        lambda: (
            SOURCE,
            "7f635adf13f105cf4ed8408766c47e612048773c",
            sync_agents.git_blob_sha(SOURCE),
        ),
    )
    monkeypatch.setattr(sync_agents, "verify_release_tag", lambda: None)
    provenance = sync_agents.refresh(tmp_path)
    assert (tmp_path / sync_agents.SOURCE_PATH).read_bytes() == SOURCE
    assert (tmp_path / sync_agents.GENERATED_PATH).read_bytes() == sync_agents.generated_agents(
        SOURCE, OVERLAY
    )
    assert provenance["content_sha256"] == sync_agents.sha256(SOURCE)
    assert provenance["expected_release_commit"] == sync_agents.EXPECTED_COMMIT
    assert sync_agents.check(tmp_path)["status"] == "PASS"


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        (b"v0.3.0", b"v0.2.0"),
        (sync_agents.EXPECTED_COMMIT.encode(), b"a" * 40),
    ],
)
def test_wrong_release_or_dependency_sha_fails_closed(original, replacement):
    altered = SOURCE.replace(original, replacement)
    with pytest.raises(sync_agents.SyncError):
        sync_agents.validate_source(altered)


def test_release_tag_must_be_annotated_and_peel_to_expected_commit():
    responses = iter(
        [
            {"object": {"type": "tag", "sha": "1" * 40}},
            {"object": {"type": "commit", "sha": sync_agents.EXPECTED_COMMIT}},
        ]
    )
    sync_agents.verify_release_tag(lambda _url: next(responses))
    responses = iter(
        [
            {"object": {"type": "tag", "sha": "1" * 40}},
            {"object": {"type": "commit", "sha": "2" * 40}},
        ]
    )
    with pytest.raises(sync_agents.SyncError, match="does not peel"):
        sync_agents.verify_release_tag(lambda _url: next(responses))
    with pytest.raises(sync_agents.SyncError, match="annotated"):
        sync_agents.verify_release_tag(
            lambda _url: {"object": {"type": "commit", "sha": sync_agents.EXPECTED_COMMIT}}
        )


@pytest.mark.parametrize("content", [b"", b" \n\t", b"not the upstream AIG template"])
def test_empty_or_invalid_upstream_document_is_rejected(content):
    with pytest.raises(sync_agents.SyncError):
        sync_agents.validate_source(content)


@pytest.mark.parametrize(
    "error",
    [
        HTTPError(sync_agents.SOURCE_URL, 503, "unavailable", {}, None),
        URLError("offline"),
    ],
)
def test_http_failures_are_reported_cleanly(monkeypatch, error):
    monkeypatch.setattr(sync_agents, "urlopen", Mock(side_effect=error))
    with pytest.raises(sync_agents.SyncError, match="request failed|HTTP status"):
        sync_agents._request(sync_agents.SOURCE_URL, limit=64, accept="text/plain")


def test_oversized_http_response_is_rejected(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 200
    response.geturl.return_value = sync_agents.SOURCE_URL
    response.read.return_value = b"x" * 65
    monkeypatch.setattr(sync_agents, "urlopen", Mock(return_value=response))
    with pytest.raises(sync_agents.SyncError, match="exceeds"):
        sync_agents._request(sync_agents.SOURCE_URL, limit=64, accept="text/plain")


def test_https_redirect_cannot_downgrade_or_change_host(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 200
    response.geturl.return_value = sync_agents.SOURCE_URL.replace("https://", "http://")
    monkeypatch.setattr(sync_agents, "urlopen", Mock(return_value=response))
    with pytest.raises(sync_agents.SyncError, match="redirect"):
        sync_agents._request(sync_agents.SOURCE_URL, limit=64, accept="text/plain")


def test_repeated_generation_is_byte_identical_and_preserves_source():
    first = sync_agents.generated_agents(SOURCE, OVERLAY)
    second = sync_agents.generated_agents(SOURCE, OVERLAY)
    assert first == second
    assert first.startswith(SOURCE)
    for safety_text in (
        "Approval alone never dispatches an effect",
        "Fail-closed recovery",
        "Do not copy, fork, reimplement, monkeypatch, or bypass",
    ):
        assert safety_text.encode() in first
    assert b"AuditGate Lab consumer rules" in first


def test_tampered_generated_agents_are_detected(tmp_path, monkeypatch):
    for path, content in (
        (sync_agents.SOURCE_PATH, SOURCE),
        (sync_agents.OVERLAY_PATH, OVERLAY),
        (sync_agents.GENERATED_PATH, sync_agents.generated_agents(SOURCE, OVERLAY)),
    ):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    monkeypatch.setattr(
        sync_agents,
        "fetch_source",
        lambda: (
            SOURCE,
            "7f635adf13f105cf4ed8408766c47e612048773c",
            sync_agents.git_blob_sha(SOURCE),
        ),
    )
    monkeypatch.setattr(sync_agents, "verify_release_tag", lambda: None)
    sync_agents.refresh(tmp_path)
    (tmp_path / sync_agents.GENERATED_PATH).write_bytes(b"tampered")
    with pytest.raises(sync_agents.SyncError, match="differs"):
        sync_agents.check(tmp_path)


def test_tampered_provenance_timestamp_is_detected(tmp_path, monkeypatch):
    (tmp_path / sync_agents.OVERLAY_PATH).parent.mkdir(parents=True)
    (tmp_path / sync_agents.OVERLAY_PATH).write_bytes(OVERLAY)
    monkeypatch.setattr(
        sync_agents,
        "fetch_source",
        lambda: (
            SOURCE,
            "7f635adf13f105cf4ed8408766c47e612048773c",
            sync_agents.git_blob_sha(SOURCE),
        ),
    )
    monkeypatch.setattr(sync_agents, "verify_release_tag", lambda: None)
    sync_agents.refresh(tmp_path)
    provenance_path = tmp_path / sync_agents.PROVENANCE_PATH
    provenance = json.loads(provenance_path.read_text("utf-8"))
    provenance["retrieved_at"] = "not-a-time"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(sync_agents.SyncError, match="timestamp"):
        sync_agents.check(tmp_path)
