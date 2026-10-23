
## AuditGate Lab consumer rules

- Repository: `miku-wwl/aig-v03-consumer-lab`, an independent local consumer integration laboratory.
- Require Python `>=3.13,<3.14` and install AIG v0.3.0 only from immutable commit `bb8e8fb1234128613a750bee17967b225072bb14`; use the installed `agentic_intent_gate.runtime` public API.
- Bind exactly one trusted `append_audit_entry/1` SIDE_EFFECT tool for target `audit-lab`, using a stable reviewed binding revision and UUIDv4 execution scope. Never register tools or trusted identities from model output.
- Use the deterministic local ModelProvider only to propose a bounded Plan. It cannot approve, authorize, select credentials, or register executors.
- Keep explicit Approval and independent execution Authorization as separate decisions. Approval alone must never cause an effect.
- Before opening a persisted Runtime store, confirm its prior owner process has stopped. Preserve store identity through restart; never reset or replay an `Unknown` Action.
- Persist Runtime state in its private gate SQLite database and business effects/receipts in a separate consumer-owned SQLite database with a unique effect key.
- Treat timeout, cancellation, lost acknowledgement, interrupted execution, and every ambiguous outcome as `Unknown`; never automatically retry or replay an Unknown Action after restart.
- Tests and the demo are offline and local only. Do not call live inference providers, cloud services, financial systems, or external mutation APIs. Automated approval is synthetic test consent; the interactive CLI requires operator input twice.
- Keep capability tokens, SQLite stores, receipts, virtual environments, and temporary state out of Git.

Required validation commands:

```bash
uv sync --locked
uv lock --check
uv run python scripts/sync_agents.py --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv pip check
git diff --check
```
