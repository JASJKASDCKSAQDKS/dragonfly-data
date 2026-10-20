# Jarvis Phase 1

Jarvis runs on Python 3.13+.

## Phase 1 setup

1. Provision a tenant as usual; new tenants receive the additive fields and
   `business_metadata`, `daily_summary`, and `schema_migrations` tables from
   `templates/standard_bar.sql`.
2. For existing tenant databases, run `POST /api/tenants/{id}/migrate` (or
   apply `templates/migrations/001_phase1.sql` with an admin MariaDB user).
   The migration only adds columns/tables/indexes and is safe to repeat.
3. Generate a deterministic demo export:

   ```bash
   python -m jarvis.seed_demo --seed 42 --output demo.sql
   # review demo.sql, then apply it to the tenant database with MariaDB
   ```

The generator creates 90 days of bar activity, 25–40 products, weekday/weekend
and evening variation, refunds/voids, low stock values, daily summaries, and
deduplication keys. Reapplying the SQL updates the same demo rows rather than
duplicating them.

## Phase 1 checklist and limitations

- [x] Additive per-tenant schema migration and demo seed generator.
- [x] Dashboard loading, empty-business onboarding checklist, import metadata,
  and explicit error/success/empty states.
- [ ] Phase 2 integrations, live POS sync, and production import scheduling
  are intentionally out of scope. The seed command emits SQL; it does not
  connect to MariaDB automatically.

## Phase 2 dashboard

Phase 2 adds the responsive owner dashboard at `/app`: Today/7 days/30 days
and custom ranges compare against the equal preceding period, using cached
`daily_summary` aggregates. It includes KPI sparklines, a comparison revenue
chart, busy-hours heatmap, top sellers, stock/reorder alerts, cash-flow
forecast, daily cached insight, assistant chips and browser speech input.
`RON` is a display-only conversion (configurable in the client; default
`1 EUR = 4.97 RON`) and the View only badge makes clear that dashboard
controls do not mutate imported sales. Run the additive migration
`templates/migrations/001_phase1.sql` (which includes version `002_phase2`)
for existing tenants. Weekly reporting is exposed as a placeholder API until
scheduled delivery is implemented.
