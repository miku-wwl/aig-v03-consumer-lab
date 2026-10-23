from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from agentic_intent_gate.runtime import ActionCommand, ExecutionSpec
from conftest import (
    admit_and_authorize,
    create_approved_run,
    open_lab_runtime,
    principal_for,
    provision_lab,
)

from aig_consumer_lab.config import load_binding
from aig_consumer_lab.persistence import AuditEffectStore


async def test_successful_effect_run_action_and_receipt_survive_runtime_restart(tmp_path):
    directory = provision_lab(tmp_path)
    command = None
    run_id = action_id = receipt_id = None
    with open_lab_runtime(directory, entry="Persisted after restart") as (runtime, store):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        command = ActionCommand(action.action_id, action.version, str(uuid4()))
        result = await runtime.gateway.execute(command, principal)
        action = result.action
        assert action.state.value == "Succeeded"
        run_id, action_id = run.run_id, action.action_id
        receipt_id = action.result["receipt_reference"]
        expected_digest = ExecutionSpec.from_compiled(action.spec).payload_digest()
        assert store.count() == 1
        assert store.get_by_receipt(receipt_id).payload_digest == expected_digest

    with open_lab_runtime(directory, entry="Persisted after restart", predecessor_stopped=True) as (
        runtime,
        store,
    ):
        principal = principal_for(runtime, directory)
        assert runtime.run_service.get(run_id).state.value == "Approved"
        recovered = runtime.gateway.get(action_id, principal)
        assert recovered.state.value == "Succeeded"
        assert recovered.result["receipt_reference"] == receipt_id
        assert [item.action_id for item in runtime.gateway.list_for_run(run_id, principal)] == [
            action_id
        ]
        assert store.count() == 1
        assert store.get_by_receipt(receipt_id).receipt_id == receipt_id
        assert store.all_effects()[0].attempt_count == 1
        replay = await runtime.gateway.execute(command, principal)
        assert replay.replayed
        assert replay.action == recovered
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1


async def test_lost_effect_commit_ack_is_unknown_and_never_replayed_after_restart(tmp_path):
    directory = provision_lab(tmp_path)
    binding = load_binding(directory / "identity.json")
    executor = AuditEffectStore(directory / "effects.sqlite3", binding, lose_ack_once=True)
    with open_lab_runtime(
        directory, entry="Committed but acknowledgement lost", executor=executor
    ) as (
        runtime,
        store,
    ):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        result = await runtime.gateway.execute(
            ActionCommand(action.action_id, action.version, str(uuid4())), principal
        )
        assert result.action.state.value == "Unknown"
        action_id, run_id = action.action_id, run.run_id
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1

    with open_lab_runtime(directory, entry="Committed but acknowledgement lost") as (
        runtime,
        store,
    ):
        principal = principal_for(runtime, directory)
        assert runtime.run_service.get(run_id).state.value == "Approved"
        recovered = runtime.gateway.get(action_id, principal)
        assert recovered.state.value == "Unknown"
        assert runtime.gateway.list_for_run(run_id, principal)[0].state.value == "Unknown"
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1


async def test_cancellation_after_effect_commit_recovers_to_unknown_without_replay(tmp_path):
    directory = provision_lab(tmp_path)
    binding = load_binding(directory / "identity.json")
    committed = asyncio.Event()
    release = asyncio.Event()
    executor = AuditEffectStore(
        directory / "effects.sqlite3",
        binding,
        committed_event=committed,
        continue_after_commit=release,
    )
    with open_lab_runtime(directory, entry="Committed before cancellation", executor=executor) as (
        runtime,
        store,
    ):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        action_id, run_id = action.action_id, run.run_id
        command = ActionCommand(action.action_id, action.version, str(uuid4()))
        task = asyncio.create_task(runtime.gateway.execute(command, principal))
        await asyncio.wait_for(committed.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.gateway.get(action_id, principal).state.value == "Unknown"
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1

    with open_lab_runtime(directory, entry="Committed before cancellation") as (runtime, store):
        principal = principal_for(runtime, directory)
        assert runtime.run_service.get(run_id).state.value == "Approved"
        assert runtime.gateway.get(action_id, principal).state.value == "Unknown"
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1
