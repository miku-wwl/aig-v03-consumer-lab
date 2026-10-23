from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from agentic_intent_gate.runtime import (
    ActionCommand,
    AdmissionCommand,
    ApprovalChoice,
    ApprovalDecisionRequest,
    Intent,
)

from aig_consumer_lab.config import SUBJECT_ID
from aig_consumer_lab.demo import provision
from aig_consumer_lab.runtime import open_lab_runtime as _open_lab_runtime


def open_lab_runtime(directory: Path, **kwargs):
    """Test-only attestation for a fresh directory and a single fixture-owned Runtime."""
    kwargs.setdefault("predecessor_stopped", True)
    return _open_lab_runtime(directory, **kwargs)


def capability_header(directory: Path) -> str:
    return "Bearer " + (directory / "capability").read_text(encoding="ascii").strip()


async def create_approved_run(runtime, *, intent: str = "Record the reviewed audit entry"):
    run = await runtime.run_service.create(Intent(intent))
    assert run.state.value == "AwaitingApproval"
    run = runtime.run_service.decide(
        run.run_id,
        ApprovalDecisionRequest(ApprovalChoice.APPROVE, run.version),
    )
    assert run.state.value == "Approved"
    return run


def principal_for(runtime, directory: Path):
    return runtime.verifier.verify(capability_header(directory))


def admit_and_authorize(runtime, run, principal):
    action = runtime.gateway.admit(
        AdmissionCommand(run.run_id, run.version, principal.subject_id, str(uuid4())),
        principal,
    ).action
    action = runtime.gateway.authorize(
        ActionCommand(action.action_id, action.version, str(uuid4())), principal
    ).action
    return action


def provision_lab(tmp_path: Path) -> Path:
    directory = tmp_path / ("lab-" + uuid4().hex)
    provision(directory)
    return directory


def raw_plan(
    entry: str = "Review passed",
    *,
    tool_name: str = "append_audit_entry",
    tool_version: str = "1",
    target: str = "audit-lab",
    arguments: dict | None = None,
    extra: dict | None = None,
) -> str:
    value = {
        "goal": "Append one reviewed audit entry",
        "target": target,
        "steps": [
            {
                "tool_name": tool_name,
                "tool_version": tool_version,
                "arguments": arguments if arguments is not None else {"entry": entry},
            }
        ],
        "risk_class": "SIDE_EFFECT",
    }
    if extra:
        value.update(extra)
    return json.dumps(value, ensure_ascii=False)


__all__ = [
    "admit_and_authorize",
    "capability_header",
    "create_approved_run",
    "principal_for",
    "provision_lab",
    "raw_plan",
    "SUBJECT_ID",
    "open_lab_runtime",
]
