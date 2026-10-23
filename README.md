# AIG v0.3.0 Consumer Integration Lab

AuditGate Lab is a small, local integration laboratory for an independent consumer of
[Agentic Intent Gate v0.3.0](https://github.com/miku-wwl/agentic-intent-gate/releases/tag/v0.3.0).
It proposes one audit entry, validates a strict Plan, asks for explicit Approval and separate
execution Authorization, then writes one durable effect and receipt to a consumer-owned SQLite
database through the installed public Runtime API.

The experiment demonstrates one trusted single-step `SIDE_EFFECT` capability. It does not
provide unrestricted multi-agent orchestration, production authentication, or external-effect
guarantees. Approval in automated tests and CI is synthetic test consent, not human approval.
No live inference, paid API, cloud provider, or external mutation is used. AIG v0.3.0 is an
immutable GitHub Release dependency; it is not published to PyPI.

## Setup

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), and Git.

```bash
uv sync --python 3.13
uv run python scripts/sync_agents.py --check
```

The lockfile pins AIG to commit
`bb8e8fb1234128613a750bee17967b225072bb14`. CI checks the committed source snapshot offline.

## Synchronize root instructions

The original upstream `AGENTS-dependence.md` is saved unchanged in
`docs/upstream/AGENTS-dependence.md`. To deliberately refresh from upstream `main`, verify its
version and the annotated v0.3.0 tag, regenerate the root file, and update provenance:

```bash
python scripts/sync_agents.py --refresh
python scripts/sync_agents.py --check
```

Normal CI never refreshes from upstream `main`.

## Run the demo

```bash
uv run python -m aig_consumer_lab demo
```

The interactive demo asks you to type `APPROVE`, then separately `AUTHORIZE`. Its fresh
private working directory is under the current user's local application data directory on
Windows and the system temporary directory on other platforms. To use a pre-provisioned or new
empty directory, pass `--directory PATH`. Reusing a provisioned directory asks you to confirm
that its previous Runtime owner has stopped before opening the durable stores.

For CI and explicit test runs only, use the synthetic fixture:

```bash
uv run python -m aig_consumer_lab demo --synthetic-test-consent
```

This mode prints `CONSENT_SOURCE=SYNTHETIC_TEST_FIXTURE`; it is not a claim of human consent.
The demo prints the actual Run ID, Action ID, effect count, and receipt reference after verifying
the Action and receipt against their separate SQLite stores.

## Acceptance checks

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

Tests use the actual installed Runtime, local SQLite databases, deterministic provider fixtures,
and explicit test-only consent. They cover Plan rejection, Approval/Authorization separation,
concurrency, idempotency, conflicting payloads, cancellation, lost acknowledgements, and restart
recovery without replay.

## Repeat this integration pattern

Another Hackathon consumer can repeat the pattern by saving and verifying the upstream consumer
instructions, pinning an annotated AIG release to its full commit in both manifest and lockfile,
inspecting the installed public Runtime API and official consumer example, then registering one
reviewed tool/schema/executor at startup. Keep its effect/receipt store separate from the Runtime
ledger. Test identity denials, approval and authorization independently, duplicate commands,
uncertain outcomes, and restart behavior before connecting any real provider or external system.
Never copy or reimplement AIG Core mechanisms in the consumer.

See [Integration Report](docs/INTEGRATION-REPORT.md) and
[Security Boundaries](docs/SECURITY-BOUNDARIES.md) for observed evidence and limitations.
