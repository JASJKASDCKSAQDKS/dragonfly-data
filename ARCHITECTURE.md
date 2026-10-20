# Jarvis architecture

Jarvis is a FastAPI application with a developer control surface and a
tenant-scoped, read-only client surface.

## Trust boundaries

- Developer endpoints require a verified developer session.
- Client endpoints require a verified client session and derive `tenant_id`
  from that session only.
- Client analytics uses the tenant's read-only MariaDB account.
- Developer provisioning uses the privileged MariaDB account only in
  developer-controlled provisioning code.
- Client AI imports only the typed analytics allowlist. It does not import
  shell, filesystem, editor, self-improvement, or provisioning tools.

## Current demo persistence

The approved Phase 1 demo preserves the existing JSON registries and
in-memory authentication service. This is intentionally transitional. The
security boundary is enforced in dependencies, route ownership, per-user
assistant session namespaces, and database credentials without requiring a
control-plane migration yet.

## Session handling

Browser clients use HTTP-only access and refresh cookies. Native clients may
continue to use the token fields returned by the API. Refresh tokens are
rotated by the existing auth service.

## Health

- `/api/health/live` is a minimal liveness probe.
- `/api/health/ready` reports process readiness and the configured model
  provider without exposing secrets or tenant data.
