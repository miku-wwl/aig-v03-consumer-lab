"""Trusted, startup-frozen identity for the one local audit capability."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from agentic_intent_gate.runtime import ToolBinding

TOOL_NAME = "append_audit_entry"
TOOL_VERSION = "1"
TARGET = "audit-lab"
ADAPTER_ID = "audit-gate-lab"
BINDING_REVISION = "audit-lab-v1"
SUBJECT_ID = "audit-lab-operator"
POLICY_REVISION = "audit-lab-policy-v1"
MAX_ENTRY_CHARS = 256
MAX_ENTRY_BYTES = 1024

ARGUMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entry"],
    "properties": {"entry": {"type": "string", "minLength": 1, "maxLength": MAX_ENTRY_CHARS}},
}


def new_binding() -> ToolBinding:
    """Construct a trusted tool binding with a new stable UUIDv4 scope."""
    return ToolBinding(
        TOOL_NAME,
        TOOL_VERSION,
        ADAPTER_ID,
        BINDING_REVISION,
        TARGET,
        str(uuid4()),
    )


def binding_json(binding: ToolBinding) -> str:
    return json.dumps(asdict(binding), sort_keys=True, separators=(",", ":"))


def save_binding(path: Path, binding: ToolBinding) -> None:
    path.write_text(json.dumps(asdict(binding), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def load_binding(path: Path) -> ToolBinding:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "tool_name",
        "tool_version",
        "adapter_id",
        "binding_revision",
        "target",
        "execution_scope",
    }:
        raise ValueError("Provisioned binding identity is invalid")
    binding = ToolBinding(**value)
    if (
        binding.tool_name != TOOL_NAME
        or binding.tool_version != TOOL_VERSION
        or binding.adapter_id != ADAPTER_ID
        or binding.binding_revision != BINDING_REVISION
        or binding.target != TARGET
    ):
        raise ValueError("Provisioned binding identity does not match the reviewed lab capability")
    return binding
