"""Interactive or explicitly synthetic offline end-to-end demonstration."""

from __future__ import annotations

import importlib.metadata
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from agentic_intent_gate.runtime import (
    ActionCommand,
    AdmissionCommand,
    ApprovalChoice,
    ApprovalDecisionRequest,
    ExecutionSpec,
    Intent,
)

from .config import MAX_ENTRY_BYTES, MAX_ENTRY_CHARS, binding_json, load_binding
from .persistence import AuditEffectStore
from .provider import DeterministicModelProvider
from .runtime import open_lab_runtime

EXPECTED_AIG_COMMIT = "bb8e8fb1234128613a750bee17967b225072bb14"
DEFAULT_ENTRY = "Deployment candidate build-42 passed review"
DEFAULT_INTENT = "Record that deployment candidate build-42 passed the review."


def verify_dependency() -> tuple[str, str]:
    version = importlib.metadata.version("agentic-intent-gate")
    direct_url = json.loads(
        importlib.metadata.distribution("agentic-intent-gate").read_text("direct_url.json") or "{}"
    )
    vcs = direct_url.get("vcs_info", {})
    if version != "0.3.0" or vcs.get("commit_id") != EXPECTED_AIG_COMMIT:
        raise RuntimeError("Installed Agentic Intent Gate does not match the immutable v0.3.0 pin")
    import agentic_intent_gate.runtime as runtime_module

    return version, str(Path(runtime_module.__file__).resolve())


def provision(directory: Path) -> None:
    from agentic_intent_gate.runtime import provision_capability

    from .config import new_binding, save_binding

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(directory.iterdir()):
        raise ValueError("Provision only an empty, private AuditGate Lab directory")
    binding = new_binding()
    provision_capability(directory / "capability")
    save_binding(directory / "identity.json", binding)
    AuditEffectStore.provision(directory / "effects.sqlite3", binding)


def _default_private_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "AuditGateLab"
        base.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="demo-", dir=base))
    return Path(tempfile.mkdtemp(prefix="aig-consumer-lab-"))


def _consent(prompt: str, expected: str, *, synthetic: bool) -> bool:
    if synthetic:
        print(f"CONSENT_SOURCE=SYNTHETIC_TEST_FIXTURE ({expected})")
        return True
    return input(f"{prompt} Type {expected} to continue: ").strip() == expected


async def run_demo(
    *,
    directory: Path | None = None,
    entry: str = DEFAULT_ENTRY,
    synthetic_test_consent: bool = False,
) -> int:
    if (
        type(entry) is not str
        or not entry
        or len(entry) > MAX_ENTRY_CHARS
        or len(entry.encode("utf-8")) > MAX_ENTRY_BYTES
    ):
        raise ValueError(
            f"Entry must be 1–{MAX_ENTRY_CHARS} characters and at most "
            f"{MAX_ENTRY_BYTES} UTF-8 bytes"
        )
    version, runtime_path = verify_dependency()
    demo_dir = Path(directory).resolve() if directory else _default_private_directory()
    if (demo_dir / "identity.json").exists():
        load_binding(demo_dir / "identity.json")
        if not _consent(
            "Confirm every earlier Runtime using this directory has stopped.",
            "PREDECESSOR_STOPPED",
            synthetic=synthetic_test_consent,
        ):
            print("PREDECESSOR_STATUS=NOT_CONFIRMED")
            return 4
        predecessor_stopped = True
    else:
        provision(demo_dir)
        predecessor_stopped = True
        print("PREDECESSOR_STATUS=FRESH_PRIVATE_DIRECTORY")

    provider = DeterministicModelProvider(entry)
    with open_lab_runtime(
        demo_dir,
        entry=entry,
        provider=provider,
        predecessor_stopped=predecessor_stopped,
    ) as (runtime, store):
        token = "Bearer " + (demo_dir / "capability").read_text(encoding="ascii").strip()
        principal = runtime.verifier.verify(token)
        run = await runtime.run_service.create(
            Intent(
                DEFAULT_INTENT if entry == DEFAULT_ENTRY else f"Record this audit entry: {entry}"
            )
        )
        persisted = runtime.run_service.get(run.run_id)
        if run.state.value != "AwaitingApproval" or persisted.to_dict() != run.to_dict():
            raise RuntimeError(f"Plan was not validated and persisted: {run.state.value}")
        print("AIG_VERSION=" + version)
        print("DEPENDENCY_PIN=VERIFIED")
        print("PLAN_VALIDATED=PASS")
        print("RUN_PERSISTED=PASS")
        print(f"RUN_ID={run.run_id}")
        print(f"PLAN_TARGET={run.plan.target}")
        print(f"PLAN_TOOL={run.plan.steps[0].tool_name}/{run.plan.steps[0].tool_version}")

        if not _consent(
            f"Approve appending this audit entry: {entry!r}.",
            "APPROVE",
            synthetic=synthetic_test_consent,
        ):
            print("APPROVAL=NOT_APPROVED")
            print("EFFECT_COUNT=" + str(store.count()))
            return 2
        run = runtime.run_service.decide(
            run.run_id,
            ApprovalDecisionRequest(ApprovalChoice.APPROVE, run.version),
        )
        if run.state.value != "Approved":
            raise RuntimeError(f"Approval did not persist: {run.state.value}")
        print("APPROVAL=APPROVED")

        admission = AdmissionCommand(run.run_id, run.version, principal.subject_id, str(uuid4()))
        action = runtime.gateway.admit(admission, principal).action
        print(f"ACTION_ID={action.action_id}")
        binding = load_binding(demo_dir / "identity.json")
        print(f"BINDING_SCOPE={binding.execution_scope}")
        if not _consent(
            f"Separately authorize executing {action.spec.tool_name} on {action.spec.target}.",
            "AUTHORIZE",
            synthetic=synthetic_test_consent,
        ):
            print("AUTHORIZATION=NOT_GRANTED")
            print("ACTION_STATE=" + action.state.value)
            print("EFFECT_COUNT=" + str(store.count()))
            return 3
        action = runtime.gateway.authorize(
            ActionCommand(action.action_id, action.version, str(uuid4())), principal
        ).action
        if action.state.value != "Authorized":
            raise RuntimeError(f"Independent authorization did not persist: {action.state.value}")
        print("AUTHORIZATION=GRANTED")

        command = ActionCommand(action.action_id, action.version, str(uuid4()))
        result = await runtime.gateway.execute(command, principal)
        action = result.action
        if action.state.value != "Succeeded" or not action.result:
            raise RuntimeError(f"Action did not succeed: {action.state.value}")
        receipt_id = action.result.get("receipt_reference")
        receipt = store.get_by_receipt(receipt_id) if isinstance(receipt_id, str) else None
        expected_digest = ExecutionSpec.from_compiled(action.spec).payload_digest()
        if (
            receipt is None
            or receipt.effect_key != action.effect_key
            or receipt.payload_digest != expected_digest
            or receipt.entry != entry
            or receipt.binding_identity != binding_json(binding)
        ):
            raise RuntimeError("Succeeded Action does not match the independent durable receipt")
        print("ACTION_STATE=" + action.state.value.upper())
        print("EFFECT_COUNT=" + str(store.count()))
        print("RECEIPT_VERIFIED=PASS")
        print(f"RECEIPT_ID={receipt.receipt_id}")
        print(f"RECEIPT_REFERENCE={receipt_id}")
        print("RUNTIME_IMPORT=" + runtime_path)
        print(
            "CONSENT_SOURCE="
            + ("SYNTHETIC_TEST_FIXTURE" if synthetic_test_consent else "INTERACTIVE_OPERATOR")
        )
        print("EVIDENCE_DIRECTORY=" + str(demo_dir))
        return 0
