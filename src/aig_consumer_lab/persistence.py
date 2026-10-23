"""Consumer-owned SQLite audit effects and durable receipt evidence."""

from __future__ import annotations

import sqlite3
from asyncio import Event
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from agentic_intent_gate.runtime import (
    EXTERNAL_PAYLOAD_REVISION,
    Outcome,
    ToolBinding,
    ToolOutcome,
)

from .config import MAX_ENTRY_BYTES, MAX_ENTRY_CHARS, binding_json


@dataclass(frozen=True)
class StoredEffect:
    effect_key: str
    payload_digest: str
    entry: str
    receipt_id: str
    binding_identity: str
    attempt_count: int


class AuditEffectStore:
    """A narrow executor backed by a database separate from AIG's gate ledger."""

    def __init__(
        self,
        path: Path,
        binding: ToolBinding,
        *,
        lose_ack_once: bool = False,
        seed_conflict_once: bool = False,
        committed_event: Event | None = None,
        continue_after_commit: Event | None = None,
    ) -> None:
        self.path = Path(path)
        self.binding = binding
        self.lose_ack_once = lose_ack_once
        self.seed_conflict_once = seed_conflict_once
        self.committed_event = committed_event
        self.continue_after_commit = continue_after_commit

    @staticmethod
    def provision(path: Path, binding: ToolBinding) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=False)
        with closing(sqlite3.connect(path)) as db:
            db.executescript(
                """
                CREATE TABLE binding_identity (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    identity_json TEXT NOT NULL
                ) STRICT;
                CREATE TABLE audit_effects (
                    effect_key TEXT PRIMARY KEY NOT NULL,
                    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
                    audit_entry TEXT NOT NULL,
                    receipt_id TEXT NOT NULL UNIQUE,
                    binding_identity TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1)
                ) STRICT;
                """
            )
            db.execute("INSERT INTO binding_identity VALUES (1, ?)", (binding_json(binding),))
            db.commit()

    def count(self) -> int:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            return int(db.execute("SELECT COUNT(*) FROM audit_effects").fetchone()[0])

    def all_effects(self) -> tuple[StoredEffect, ...]:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT effect_key, payload_digest, audit_entry, receipt_id, "
                "binding_identity, attempt_count FROM audit_effects ORDER BY rowid"
            ).fetchall()
        return tuple(StoredEffect(*row) for row in rows)

    def get_by_receipt(self, receipt_id: str) -> StoredEffect | None:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT effect_key, payload_digest, audit_entry, receipt_id, "
                "binding_identity, attempt_count FROM audit_effects WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return StoredEffect(*row) if row else None

    async def execute(self, spec, effect_key: str, context) -> ToolOutcome:
        def evidence(category, *, receipt: str | None = None, reason: str | None = None):
            return ToolOutcome(
                category,
                effect_key,
                spec.execution_scope,
                spec.target,
                spec.payload_digest(),
                receipt,
                reason,
            )

        try:
            arguments = dict(spec.arguments)
            entry = arguments.get("entry")
            if (
                not self.binding.matches(spec)
                or spec.identity_revision != EXTERNAL_PAYLOAD_REVISION
                or set(arguments) != {"entry"}
                or type(entry) is not str
                or not 1 <= len(entry) <= MAX_ENTRY_CHARS
                or len(entry.encode("utf-8", errors="strict")) > MAX_ENTRY_BYTES
                or str(UUID(effect_key, version=4)) != effect_key
                or str(UUID(context.attempt_id, version=4)) != context.attempt_id
            ):
                return evidence(Outcome.CONFIRMED_FAILURE, reason="INPUT_REJECTED")
            if context.expired():
                return ToolOutcome(Outcome.UNKNOWN_OUTCOME)

            identity = binding_json(self.binding)
            digest = spec.payload_digest()
            with closing(
                sqlite3.connect(
                    self.path.resolve().as_uri() + "?mode=rw",
                    uri=True,
                    timeout=2,
                )
            ) as db:
                db.execute("BEGIN IMMEDIATE")
                stored_identity = db.execute(
                    "SELECT identity_json FROM binding_identity WHERE singleton = 1"
                ).fetchone()
                if stored_identity != (identity,):
                    db.rollback()
                    return evidence(Outcome.CONFIRMED_FAILURE, reason="STORE_IDENTITY_MISMATCH")

                existing = db.execute(
                    "SELECT payload_digest, audit_entry, receipt_id, binding_identity "
                    "FROM audit_effects WHERE effect_key = ?",
                    (effect_key,),
                ).fetchone()
                if self.seed_conflict_once and existing is None:
                    self.seed_conflict_once = False
                    conflict_receipt = str(uuid4())
                    conflict_digest = "0" * 64 if digest != "0" * 64 else "1" * 64
                    db.execute(
                        "INSERT INTO audit_effects VALUES (?, ?, ?, ?, ?, 1)",
                        (
                            effect_key,
                            conflict_digest,
                            "Preexisting conflicting receipt fixture",
                            conflict_receipt,
                            identity,
                        ),
                    )
                    db.commit()
                    return evidence(Outcome.CONFIRMED_FAILURE, reason="PAYLOAD_CONFLICT")

                if existing is not None:
                    if existing[0] != digest:
                        db.rollback()
                        return evidence(Outcome.CONFIRMED_FAILURE, reason="PAYLOAD_CONFLICT")
                    if existing[1] != entry or existing[3] != identity:
                        db.rollback()
                        return ToolOutcome(Outcome.UNKNOWN_OUTCOME)
                    db.execute(
                        "UPDATE audit_effects SET attempt_count = attempt_count + 1 "
                        "WHERE effect_key = ?",
                        (effect_key,),
                    )
                    db.commit()
                    return evidence(Outcome.SUCCESS, receipt=existing[2])

                receipt_id = str(uuid4())
                db.execute(
                    "INSERT INTO audit_effects VALUES (?, ?, ?, ?, ?, 1)",
                    (effect_key, digest, entry, receipt_id, identity),
                )
                if context.expired():
                    db.rollback()
                    return ToolOutcome(Outcome.UNKNOWN_OUTCOME)
                db.commit()
                if self.committed_event is not None:
                    self.committed_event.set()
                if self.continue_after_commit is not None:
                    await self.continue_after_commit.wait()
                if self.lose_ack_once:
                    self.lose_ack_once = False
                    raise sqlite3.OperationalError("Injected lost effect commit acknowledgement")
                if context.expired():
                    return ToolOutcome(Outcome.UNKNOWN_OUTCOME)
                return evidence(Outcome.SUCCESS, receipt=receipt_id)
        except Exception:
            # An exception does not prove that the independent effect transaction rolled back.
            return ToolOutcome(Outcome.UNKNOWN_OUTCOME)
