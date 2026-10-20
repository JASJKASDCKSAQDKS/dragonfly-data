# Jarvis local runbook

## Start locally

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env` and set local credentials.
3. Start MariaDB if tenant analytics are needed.
4. Start the app with:

   ```bash
   ./start.sh
   ```

5. Open `http://localhost:8000/login`.

## Client portal demo

The replacement React client is kept under `frontend/` and does not replace
the existing static dashboard yet:

```bash
cd frontend
npm ci
npm run dev
```

For a production bundle, run `npm run build` in `frontend/`. The portal uses
the same cookie-authenticated API and can fall back to its last loaded
dashboard snapshot while offline.

For a no-database visual preview using fictional data only, open
`http://localhost:8000/demo`. This route is deliberately separate from
authenticated tenant dashboards and must never be used for real business data.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

MariaDB integration and cross-tenant provisioning tests are opt-in:

```bash
JARVIS_RUN_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_cross_tenant_security.py
```

## Health checks

```bash
curl http://localhost:8000/api/health/live
curl http://localhost:8000/api/health/ready
```

CI runs both the backend test suite and the frontend TypeScript/Vite build.

## Incident actions

- Suspend the affected user or tenant through the developer console/API.
- Rotate the JWT secret and restart all workers if token compromise is
  suspected.
- Revoke refresh tokens by restarting the demo service; durable revocation is
  part of the planned control-plane migration.
- Preserve audit logs and application logs before deleting data.

Never delete tenant databases or customer exports without explicit approval and
a verified backup.

## Import status and GDPR requests

Developer sessions can inspect demo import metadata:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/tenants/1/imports
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/tenants/1/privacy-requests
```

Queue a request (this does not execute it):

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"request_type":"export"}' \
  http://localhost:8000/api/tenants/1/privacy-requests
```

The demo stores only request metadata in JSON. Operators must review
retention/legal-hold requirements and use an approved, audited fulfilment
process; there is no automatic deletion or export worker.
