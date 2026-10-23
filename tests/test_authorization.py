from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from agentic_intent_gate.runtime import (
    ActionCode,
    ActionCommand,
    ActionError,
    AdmissionCommand,
    ApprovalChoice,
    ApprovalDecisionRequest,
    CapabilityVerifier,
    Intent,
    provision_capability,
)
from conftest import create_approved_run, open_lab_runtime, principal_for, provision_lab, raw_plan

from aig_consumer_lab.config import SUBJECT_ID, load_binding


async def test_missing_approval_cannot_admit_an_action(tmp_path):
    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await runtime.run_service.create(Intent("Record Reviewed"))
        principal = principal_for(runtime, directory)
        with pytest.raises(ActionError):
            runtime.gateway.admit(
                AdmissionCommand(run.run_id, run.version, principal.subject_id, str(uuid4())),
                principal,
            )
        assert store.count() == 0
        assert runtime.gateway.list_for_run(run.run_id, principal) == ()


async def test_stale_approval_version_is_rejected_without_effect(tmp_path):
    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await runtime.run_service.create(Intent("Record Reviewed"))
        with pytest.raises(Exception, match="Run version does not match expected_version"):
            runtime.run_service.decide(
                run.run_id,
                ApprovalDecisionRequest(ApprovalChoice.APPROVE, run.version - 1),
            )
        assert runtime.run_service.get(run.run_id).state.value == "AwaitingApproval"
        assert store.count() == 0


@pytest.mark.parametrize("mismatch", ["scope", "binding_revision"])
async def test_wrong_scope_or_binding_revision_cannot_admit(tmp_path, mismatch):
    from dataclasses import replace

    directory = provision_lab(tmp_path)
    binding = load_binding(directory / "identity.json")
    wrong = (
        replace(binding, execution_scope=str(uuid4()))
        if mismatch == "scope"
        else replace(binding, binding_revision="unreviewed-revision")
    )
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await create_approved_run(runtime)
        token_path = tmp_path / f"{mismatch}-capability"
        provision_capability(token_path)
        token = token_path.read_text("ascii").strip()
        foreign_verifier = CapabilityVerifier(
            token,
            subject_id=SUBJECT_ID,
            binding=wrong,
            operations=("read", "admit", "authorize", "execute"),
        )
        foreign_principal = foreign_verifier.verify("Bearer " + token)
        with pytest.raises(ActionError) as raised:
            runtime.gateway.admit(
                AdmissionCommand(
                    run.run_id, run.version, foreign_principal.subject_id, str(uuid4())
                ),
                foreign_principal,
            )
        assert raised.value.code is ActionCode.NOT_AUTHORIZED
        assert runtime.gateway.list_for_run(run.run_id, principal_for(runtime, directory)) == ()
        assert store.count() == 0


async def test_missing_and_invalid_authorization_produce_no_effect(tmp_path):
    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        from agentic_intent_gate.runtime import AdmissionCommand

        action = runtime.gateway.admit(
            AdmissionCommand(run.run_id, run.version, principal.subject_id, str(uuid4())), principal
        ).action
        with pytest.raises(ActionError):
            await runtime.gateway.execute(
                ActionCommand(action.action_id, action.version, str(uuid4())), principal
            )
        with pytest.raises(ActionError) as raised:
            runtime.verifier.verify("Bearer invalid")
        assert raised.value.code is ActionCode.AUTHENTICATION_REQUIRED
        assert store.count() == 0


async def test_wrong_scope_authorization_is_rejected_and_does_not_dispatch(tmp_path):
    directory = provision_lab(tmp_path)
    binding = load_binding(directory / "identity.json")
    wrong = replace(binding, execution_scope=str(uuid4()))
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = runtime.gateway.admit(
            AdmissionCommand(run.run_id, run.version, principal.subject_id, str(uuid4())), principal
        ).action
        token_path = tmp_path / "wrong-auth-capability"
        provision_capability(token_path)
        token = token_path.read_text("ascii").strip()
        wrong_verifier = CapabilityVerifier(
            token,
            subject_id=SUBJECT_ID,
            binding=wrong,
            operations=("read", "admit", "authorize", "execute"),
        )
        with pytest.raises(ActionError):
            runtime.gateway.authorize(
                ActionCommand(action.action_id, action.version, str(uuid4())),
                wrong_verifier.verify("Bearer " + token),
            )
        assert store.count() == 0
        assert runtime.gateway.get(action.action_id, principal).state.value != "Authorized"


@pytest.mark.parametrize(
    "raw",
    [
        raw_plan(tool_name="unknown_tool"),
        raw_plan(tool_version="2"),
        raw_plan(target="wrong-target"),
        raw_plan(arguments={"entry": "valid", "extra": "denied"}),
        raw_plan(arguments={"entry": ""}),
        raw_plan(arguments={"entry": "x" * 257}),
        raw_plan(arguments={"entry": "x" * 5000}),
        raw_plan(extra={"execution_timeout_seconds": 15}),
    ],
)
async def test_untrusted_plan_identity_schema_size_and_budget_are_rejected(tmp_path, raw):
    from aig_consumer_lab.provider import DeterministicModelProvider

    directory = provision_lab(tmp_path)
    with open_lab_runtime(
        directory,
        entry="ignored",
        provider=DeterministicModelProvider("ignored", raw_plan=raw),
    ) as (runtime, store):
        run = await runtime.run_service.create(Intent("Record an audit entry"))
        assert run.state.value != "AwaitingApproval"
        assert run.error is not None
        assert runtime.gateway.list_for_run(run.run_id, principal_for(runtime, directory)) == ()
        assert store.count() == 0


@pytest.mark.parametrize("budget", [True, 0, -1, 16, float("inf"), float("nan")])
async def test_invalid_or_untrusted_execution_budgets_are_rejected(tmp_path, budget):
    directory = provision_lab(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        with open_lab_runtime(
            directory,
            entry="Reviewed",
            execution_timeout_seconds=budget,
        ):
            pytest.fail("invalid execution budget unexpectedly opened the Runtime")
