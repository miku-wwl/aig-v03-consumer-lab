"""Composition of one consumer-owned binding with the installed AIG Runtime."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agentic_intent_gate.runtime import (
    BoundCapabilityAuthorization,
    CapabilityVerifier,
    ExecutableRegistry,
    ToolCapability,
    open_runtime,
)

from .config import ARGUMENT_SCHEMA, POLICY_REVISION, SUBJECT_ID, load_binding
from .persistence import AuditEffectStore
from .provider import DeterministicModelProvider


@contextmanager
def open_lab_runtime(
    directory: Path,
    *,
    entry: str,
    provider=None,
    executor: AuditEffectStore | None = None,
    predecessor_stopped: bool = False,
    execution_timeout_seconds: int | float = 5,
) -> Iterator[tuple[object, AuditEffectStore]]:
    directory = Path(directory).resolve()
    binding = load_binding(directory / "identity.json")
    token = (directory / "capability").read_text(encoding="ascii").strip()
    if not token:
        raise ValueError("Provisioned capability token is empty")
    store = executor or AuditEffectStore(directory / "effects.sqlite3", binding)
    capability = ToolCapability(binding, "Append one reviewed audit entry", ARGUMENT_SCHEMA)
    verifier = CapabilityVerifier(
        token,
        subject_id=SUBJECT_ID,
        binding=binding,
        operations=("read", "admit", "authorize", "execute"),
    )
    registry = ExecutableRegistry(store, binding=binding)
    policy = BoundCapabilityAuthorization(verifier, policy_revision=POLICY_REVISION)
    with open_runtime(
        gate_path=directory / "gate.sqlite3",
        provider=provider or DeterministicModelProvider(entry),
        capability=capability,
        registry=registry,
        verifier=verifier,
        policy=policy,
        predecessor_stopped=predecessor_stopped,
        execution_timeout_seconds=execution_timeout_seconds,
    ) as runtime:
        yield runtime, store
