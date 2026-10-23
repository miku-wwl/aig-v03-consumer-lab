# Integration Report

## Purpose

This experiment qualifies an independent local consumer integration of Agentic Intent Gate
(AIG) v0.3.0. AuditGate Lab proposes one `append_audit_entry/1` Plan, stores a persistent Run,
requires Approval and separate execution Authorization, and executes one local SQLite-backed
effect through AIG's installed public Runtime.

## Upstream instructions and release identity

- Upstream instructions URL: <https://raw.githubusercontent.com/miku-wwl/agentic-intent-gate/main/docs/AGENTS-dependence.md>
- Retrieved from upstream `main` commit: `7f635adf13f105cf4ed8408766c47e612048773c`
- Git blob identity: `f14307dcc124a0eaefc24dbc3cb64643f35b1fa9`
- Downloaded content SHA-256: `499f7c64b551dbfd48d640606da0b4ebb9e67c39e9544ed7eb120f08d732d10e`
- AIG annotated tag: `v0.3.0`; observed tag object `28af5eccf287f70b63f20386010e5747e1511e9b` peels to required commit `bb8e8fb1234128613a750bee17967b225072bb14`.
- Generated root `AGENTS.md` SHA-256 after the final overlay update: `b5db5e64eed436a7c9bf9b2021c0f9a6ec8fdb0bda61c5c39fde8dc2f0cf998f`.
- `scripts/sync_agents.py --refresh` fetched the raw HTTPS document, matched its Git blob against the exact main-commit contents, verified the annotated v0.3.0 tag through GitHub's API, checked required release/security statements, and generated the local root instructions from the unchanged source plus `config/agents-overlay.md`.
- `scripts/sync_agents.py --check` is an offline integrity and reproducibility check. Normal CI does not track upstream `main`.

## Dependency and environment

- Python: `3.13.9` (`D:\anaconda3\python.exe` in the development environment).
- uv: `0.11.16`.
- Installed distribution: `agentic-intent-gate==0.3.0`.
- Installed Runtime import: `.venv/Lib/site-packages/agentic_intent_gate/runtime.py`.
- Installed `direct_url.json` identifies Git commit and requested revision as
  `bb8e8fb1234128613a750bee17967b225072bb14`.
- `pyproject.toml` uses the full immutable HTTPS Git revision. `uv.lock` resolves the same
  immutable commit. No AIG source is editable or copied into this repository.
- Runtime's observed public `open_runtime` signature includes the backward-compatible
  `execution_timeout_seconds=5` default. This integration uses the default five-second budget.

## Consumer lifecycle

The consumer composes one startup-frozen `ToolBinding` with exact identity:

```text
tool=append_audit_entry
version=1
target=audit-lab
adapter=audit-gate-lab
binding_revision=audit-lab-v1
execution_scope=<persisted UUIDv4>
```

The deterministic provider returns only the bounded Plan proposal. The AIG public
`PlanningService`, `RunService`, and Action gateway perform validation, persistence, Approval,
admission, Authorization, durable claim, execution, and terminal state transitions. The
consumer-owned effect database is separate from the Runtime gate database. Each effect row
persists its key, payload digest, entry, receipt UUID, binding identity, and executor-attempt
count; effect key and receipt ID are independently unique.

The default interactive command asks the operator to type `APPROVE` and then separately
`AUTHORIZE`. The local acceptance run used the explicitly synthetic fixture flag, which printed
`CONSENT_SOURCE=SYNTHETIC_TEST_FIXTURE`; it is not human-approval evidence.

## Local evidence

Final local CLI smoke test (synthetic local consent):

```text
AIG_VERSION=0.3.0
DEPENDENCY_PIN=VERIFIED
PLAN_VALIDATED=PASS
RUN_PERSISTED=PASS
APPROVAL=APPROVED
AUTHORIZATION=GRANTED
ACTION_STATE=SUCCEEDED
EFFECT_COUNT=1
RECEIPT_VERIFIED=PASS
RUN_ID=40bc29a8-70cd-4bbe-9ef5-9744d6745e58
ACTION_ID=50006e13-e55f-402a-a4e1-1cfa86b357a5
RECEIPT_REFERENCE=e48f6c47-9e8a-4e5c-80bf-a342fbacbd4a
```

The CLI verified that the receipt's database row matched the succeeded Action's effect key,
independently recomputed payload digest, requested entry, and full binding identity. The
consumer tests additionally inspect SQLite rows after approval-only, denial, success, duplicate,
concurrent, conflicting-payload, cancellation, acknowledgement-loss, and restart paths.

The suite distinguishes template synchronization, dependency metadata, Runtime integration,
security/authorization, idempotency, and persistence/recovery in separate test modules. The full
acceptance suite completed with 47 passed and zero failures:

| Test module | Coverage |
| --- | --- |
| `tests/test_agents_sync.py` | Real snapshot checks, GitHub fetch/tag failure handling, reproducibility, provenance and tamper detection |
| `tests/test_dependency.py` | Installed AIG version, direct Git metadata, import location and lock pin |
| `tests/test_integration.py` | Validated Plan, Run, separate Approval/Authorization, receipt, concurrency and conflicting effect |
| `tests/test_authorization.py` | Missing/stale approval, wrong identity/scope/revision, invalid auth, malformed/oversized Plan and budget rejection |
| `tests/test_idempotency.py` | Duplicate and concurrent commands without a second effect |
| `tests/test_recovery.py` | Durable success, restart, lost acknowledgment, cancellation and no replay |

## Validation evidence

| Command or gate | Result |
| --- | --- |
| `uv sync --locked` | PASS; 33 packages checked |
| `uv lock --check` | PASS |
| `uv run python scripts/sync_agents.py --check` | PASS; saved upstream and generated hashes matched |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 21 files formatted |
| `uv run pytest -q` | PASS; 47 passed, 0 failed |
| `uv pip check` | PASS; 33 installed packages compatible |
| `git diff --check` | PASS; checked after the final report update and again on the staged diff |
| Fresh Python 3.13 environment outside checkout | PASS; wheel install, `uv pip check`, isolated `-I` CLI, direct SQLite receipt verification |
| GitHub push and remote SHA comparison | PASS; local `HEAD`, `origin/main`, `git ls-remote`, and GitHub API agree on `ca34645ce7a6f1e546c14ed72fd10279b0e0f7f8` |
| GitHub Actions workflow | PASS; [run 39875393218](https://github.com/miku-wwl/aig-v03-consumer-lab/actions/runs/39875393218), all 12 qualification steps succeeded on that commit |

Isolated qualification used build directory
`C:\Users\weila\AppData\Local\Temp\aig-v03-consumer-lab-build-20261023-125511` and
Python environment
`C:\Users\weila\AppData\Local\Temp\aig-v03-consumer-lab-isolated-20261023-125511`, outside
the source checkout. A clean `-I` subprocess imported
`agentic_intent_gate.runtime` from that environment, ran the wheel-installed CLI with a fresh
SQLite store, and independently queried one effect row matching the printed receipt UUID, target,
payload digest, and binding identity.

## Limitations

- No live Ollama, OpenAI, Anthropic, paid inference, cloud API, financial transaction, or external
  mutation was used.
- Synthetic approval and authorization fixtures are test-only. No human-approved run is claimed.
- Local SQLite evidence does not prove exactly-once remote effects.
- The Runtime is used for one trusted single-step SIDE_EFFECT capability; unrestricted
  multi-agent orchestration, distributed HA, multi-tenancy, and production deployment are out of
  scope.
- The fifteen-second execution profile and public Unknown reconciliation are not used.

## Remote delivery

The target repository already existed as a private GitHub repository with default branch `main`
and initial commit `4b394644c15ba1c9d36bb7697abb3cd0185ee756`. It was reused without changing
visibility. HTTPS push of qualification commit `ca34645ce7a6f1e546c14ed72fd10279b0e0f7f8` was
verified against the local branch, tracking ref, `git ls-remote`, and GitHub API. Workflow run
`39875393218` completed successfully for that commit; checkout, locked install, pin and snapshot
checks, Ruff, all tests, synthetic CLI smoke, dependency check, and whitespace check each passed.

The documentation was then updated with these observed remote results. That follow-up commit also
triggers the same workflow; its run is checked after push and reported as the latest remote result.
