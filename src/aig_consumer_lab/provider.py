"""Deterministic local planning boundary for tests and the offline demonstration."""

from __future__ import annotations

import json

from .config import TARGET, TOOL_NAME, TOOL_VERSION


class DeterministicModelProvider:
    """Propose one bounded audit Plan; this provider has no authority to execute it."""

    def __init__(self, entry: str, *, raw_plan: str | None = None) -> None:
        self.entry = entry
        self.raw_plan = raw_plan

    async def generate_plan(self, intent, **_kwargs: object) -> str:
        del intent  # Planning is deterministic and intentionally does not infer authority.
        if self.raw_plan is not None:
            return self.raw_plan
        return json.dumps(
            {
                "goal": "Append one reviewed audit entry",
                "target": TARGET,
                "steps": [
                    {
                        "tool_name": TOOL_NAME,
                        "tool_version": TOOL_VERSION,
                        "arguments": {"entry": self.entry},
                    }
                ],
                "risk_class": "SIDE_EFFECT",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
