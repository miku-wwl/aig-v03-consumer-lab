from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from agentic_intent_gate.runtime import ActionCommand, ActionError
from conftest import (
    admit_and_authorize,
    create_approved_run,
    open_lab_runtime,
    principal_for,
    provision_lab,
)


async def test_concurrent_duplicate_execution_commands_create_one_effect(tmp_path):
    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="One durable entry") as (runtime, store):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        command = ActionCommand(action.action_id, action.version, str(uuid4()))
        first, second = await asyncio.gather(
            runtime.gateway.execute(command, principal),
            runtime.gateway.execute(command, principal),
        )
        assert first.replayed != second.replayed
        assert {first.action.state.value, second.action.state.value} == {"Succeeded"}
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1


async def test_duplicate_with_different_idempotency_key_cannot_reexecute_terminal_action(tmp_path):
    directory = provision_lab(tmp_path)
    with open_lab_runtime(directory, entry="One durable entry") as (runtime, store):
        run = await create_approved_run(runtime)
        principal = principal_for(runtime, directory)
        action = admit_and_authorize(runtime, run, principal)
        original = await runtime.gateway.execute(
            ActionCommand(action.action_id, action.version, str(uuid4())), principal
        )
        with pytest.raises(ActionError):
            await runtime.gateway.execute(
                ActionCommand(action.action_id, original.action.version, str(uuid4())), principal
            )
        assert original.action.state.value == "Succeeded"
        assert store.count() == 1
        assert store.all_effects()[0].attempt_count == 1
