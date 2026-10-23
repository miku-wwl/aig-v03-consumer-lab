from __future__ import annotations

from uuid import uuid4

from agentic_intent_gate.runtime import (
    ActionCommand,
    ApprovalChoice,
    ApprovalDecisionRequest,
    ExecutionSpec,
    Intent,
)
from conftest import (
    admit_and_authorize,
    create_approved_run,
    open_lab_runtime,
    principal_for,
    provision_lab,
)

from aig_consumer_lab.config import binding_json, load_binding
from aig_consumer_lab.persistence import AuditEffectStore


async def test_valid_plan_runs_through_real_aig_gateway_to_verified_sqlite_receipt(tmp_path):
    directory = provision_lab(tmp_path)
    entry = "Deployment candidate build-42 passed review"
    with open_lab_runtime(directory, entry=entry) as (runtime, store):
        run = await runtime.run_service.create(
            Intent("Record that deployment candidate build-42 passed the review.")
        )
        assert run.state.value == "AwaitingApproval"
        assert runtime.run_service.get(run.run_id).to_dict() == run.to_dict()
        assert store.count() == 0

        run = runtime.run_service.decide(
            run.run_id, ApprovalDecisionRequest(ApprovalChoice.APPROVE, run.version)
        )
        assert run.state.value == "Approved"
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        assert action.state.value == "Authorized"
        assert store.count() == 0

        command = ActionCommand(action.action_id, action.version, str(uuid4()))
        result = await runtime.gateway.execute(command, principal)
        action = result.action
        assert not result.replayed
        assert action.state.value == "Succeeded"
        assert store.count() == 1
        assert len(store.all_effects()) == 1
        effect = store.get_by_receipt(action.result["receipt_reference"])
        assert effect is not None
        assert effect.effect_key == action.effect_key
        assert effect.payload_digest == ExecutionSpec.from_compiled(action.spec).payload_digest()
        assert effect.entry == entry
        assert effect.binding_identity == binding_json(load_binding(directory / "identity.json"))
        assert effect.attempt_count == 1


async def test_provider_output_does_not_grant_approval_or_authorization(tmp_path):
    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await runtime.run_service.create(Intent("Record Reviewed"))
        assert run.state.value == "AwaitingApproval"
        assert store.count() == 0
        assert runtime.gateway.list_for_run(run.run_id, principal_for(runtime, directory)) == ()


async def test_duplicate_command_is_replayed_without_a_second_effect(tmp_path):
    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        command = ActionCommand(action.action_id, action.version, str(uuid4()))
        first = await runtime.gateway.execute(command, principal)
        replay = await runtime.gateway.execute(command, principal)
        assert first.action.state.value == "Succeeded"
        assert replay.replayed
        assert replay.action == first.action
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1


async def test_concurrent_duplicate_commands_admit_at_most_one_effect(tmp_path):
    import asyncio

    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="Reviewed") as (runtime, store):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        command = ActionCommand(action.action_id, action.version, str(uuid4()))
        results = await asyncio.gather(
            runtime.gateway.execute(command, principal),
            runtime.gateway.execute(command, principal),
        )
        assert sorted(result.replayed for result in results) == [False, True]
        assert all(result.action.state.value == "Succeeded" for result in results)
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1


async def test_preexisting_conflicting_effect_payload_is_safely_classified(tmp_path):
    directory = provision_lab(tmp_path)
    binding = load_binding(directory / "identity.json")
    executor = AuditEffectStore(directory / "effects.sqlite3", binding, seed_conflict_once=True)
    with open_lab_runtime(directory, entry="Requested audit entry", executor=executor) as (
        runtime,
        store,
    ):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        result = await runtime.gateway.execute(
            ActionCommand(action.action_id, action.version, str(uuid4())), principal
        )
        assert result.action.state.value == "Failed"
        assert result.action.result["receipt_reference"] is None
        assert store.count() == 1
        effect = store.all_effects()[0]
        assert effect.entry == "Preexisting conflicting receipt fixture"
        assert effect.entry != "Requested audit entry"
        assert effect.attempt_count == 1
