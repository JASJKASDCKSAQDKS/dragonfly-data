# Jarvis security model

## Authentication

- Passwords use Argon2id.
- Access tokens are short-lived.
- Refresh tokens are rotated and stored as hashes in the current demo service.
- Browser sessions use HTTP-only cookies.
- Developer MFA is supported through TOTP. Production startup requires
  `DEVELOPER_MFA_REQUIRED=true`; the local development environment keeps this
  false so the existing bootstrap flow remains usable.
- Failed login attempts are rate limited and subject to account lockout.

## Tenant isolation

Client tenant resolution is derived from the verified authentication context.
Client requests cannot select a tenant, database name, or database credentials.
Analytics connections use the tenant read-only account and fixed,
parameterized queries.

Assistant conversation IDs are namespaced by authenticated user inside each
tenant's conversation store. A user from another tenant or account cannot
retrieve a session by guessing its public identifier.

## AI safety

The client assistant has a separate allowlist of read-only analytics methods.
It cannot execute shell commands, access files, modify code, provision
databases, run free-form SQL, or change its own behavior.

Database and import content is treated as untrusted data. It must never be
interpreted as instructions.

## Import and GDPR demo controls

- Developer-only `GET /api/tenants/{id}/imports` and
  `GET /api/tenants/{id}/imports/{job_id}` expose job metadata only
  (status, counts, filename, and timestamps), never imported rows or
  credentials.
- Developer-only privacy requests (`POST .../privacy-requests` with
  `export` or `deletion`) are queued in a 0600 JSON registry for operator
  review. They are request-only in this demo: no endpoint automatically
  exports data or deletes a tenant.
- Fulfilment must verify identity, legal holds, retention obligations,
  backups, and tenant scope before a separately reviewed worker performs it.

## Reporting

Report suspected security issues privately to the project owner. Do not put
credentials, access tokens, `.env`, database dumps, or customer exports into
source control or issue reports.
