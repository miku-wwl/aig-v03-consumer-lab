# Security Boundaries

AuditGate Lab is an offline consumer integration experiment. Its trusted Python code, capability
token, local files, and host process run under the current OS user. It is not a sandbox or a
production authentication system.

## Authority boundaries

- The deterministic provider returns only a candidate Plan. The AIG Runtime validates the Plan
  against a closed one-field schema and the startup-frozen binding.
- The operator's `APPROVE` input records Approval. It does not authorize or execute an Action.
- The separate `AUTHORIZE` input is required before the gateway claims execution.
- Automated tests and CI explicitly use synthetic consent fixtures. They do not claim human
  approval.
- Exactly one trusted tool is registered: `append_audit_entry/1` on `audit-lab`, with a stable
  binding revision and a persisted UUIDv4 execution scope.

## Persistence and uncertainty

The Runtime's gate/Action ledger and the consumer's audit effects/receipts use different SQLite
files. The effect store binds each effect key to the payload digest, entry, receipt UUID, and full
binding identity, with a unique constraint on effect key and receipt.

The Runtime's durable Action claim and idempotency lifecycle remain in control. A timeout,
cancellation, lost commit acknowledgement, or other ambiguous post-dispatch condition is treated
as `Unknown`. Recovery does not call the executor again. The tests verify local SQLite durability
and fail-closed behavior; they do not prove exactly-once behavior for a remote service.

## Explicit limits

- No Ollama, OpenAI, Anthropic, or other inference endpoint is contacted.
- No cloud API, payment, financial transaction, or external mutation is performed.
- No claim is made about distributed execution, high availability, multi-tenancy, unrestricted
  tools, multi-step orchestration, or production deployment.
- Local bearer capability files and scripted test consent are for this isolated lab only.
- The Runtime's default five-second adapter budget is used. The fifteen-second profile is not
  enabled.
- Temporary directories, virtual environments, capability tokens, and SQLite files are ignored
  by Git and must remain outside commits.
