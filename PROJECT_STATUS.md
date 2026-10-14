# Project status

AgentForge is implemented as a runnable Docker Compose system: FastAPI, a Redis-backed worker, PostgreSQL, a React dashboard, Prometheus, and Grafana.

## Implemented

- Registration, login, refresh-token rotation, logout, profile update, and password change. Passwords are bcrypt hashes. Access is enforced with JWTs and role checks.
- Tenant isolation: agents, tasks, records, activity, and dead letters are scoped to the owner. Other users receive 404. Admin overview returns counts only.
- Agent create, edit, start, pause, and archive. Tasks can be queued, cancelled, retried, and inspected.
- Allowlisted tools: HTTP request, text transform, conditional branch, and tenant-scoped record storage. No shell or generated-code execution.
- SSRF checks reject non-HTTP schemes, URL credentials, localhost, private, link-local, reserved, metadata, and unresolved-private DNS answers. Redirect targets are checked again.
- PostgreSQL is the durable store for users, agents, tasks, steps, activity, records, and dead letters. Alembic migration `0001_initial` creates that schema.
- Redis queues work, delays retries, rate-limits requests, stores refresh tokens, caches the dashboard briefly, and publishes live events.
- Retries use exponential backoff until `max_retries`. Exhausted and permanent failures are dead-lettered. Idempotency keys collapse duplicate creates. Expired worker leases are requeued.
- Task statuses: pending, queued, running, completed, failed, cancelled.
- Live updates use a Server-Sent Events stream that reads PostgreSQL and Redis.
- Health, readiness, and Prometheus metrics are exposed. Grafana is provisioned with an AgentForge dashboard.
- The mock LLM runs the demo triage workflow without an API key. An OpenAI-compatible provider is available when `LLM_API_KEY` is set.
- Seed data creates `demo@example.com` / `DemoPass123!`, `admin@example.com` / `AdminPass123!`, the Support Triage agent, and one completed execution.

## Publication audit

On 14 October 2026 the tree was reviewed for public GitHub publication. No `.env` file is present. Demo passwords and the development JWT secret are public local defaults, and production startup rejects them. The folder was not a Git repository, so there is no commit history to purge.

The same day: backend pytest reported 45 passed, frontend vitest reported 5 passed, the production frontend build succeeded, `docker compose config --quiet` exited 0, and `python scripts/verify_http.py` exited 0 against the Compose stack. `npm audit --omit=dev` reports two moderate React Router advisories whose suggested fix is a major upgrade. That upgrade was not applied.

## Verification

Commands run on this machine against the final source:

- `backend/.venv` pytest: 45 passed.
- `frontend` vitest: 5 passed. `npm run build` (`tsc --noEmit` and Vite) succeeded locally and again inside the frontend image.
- `docker compose up --build -d` started Postgres, Redis, API, worker, frontend, Prometheus, and Grafana. API readiness became healthy.
- `scripts/verify_http.py` against `http://localhost:8000` exited 0. It registered a user, logged in, created and started an agent, queued the urgent billing message, confirmed an idempotent replay, read the SSE stream, and observed a completed task. The stored summary was: trim, `classify_urgency=high`, `branch=priority`, and a stored record. A second user received 404 for that agent. An HTTP task aimed at `169.254.169.254` finished `failed` with `dead_letter=true`. The demo user could log in and the dashboard reported at least one completed task with database and Redis checks ok.
- `http://localhost:8080/` returned 200 and the AgentForge shell. Login through the frontend proxy at `/api/v1/auth/login` returned 200 for `demo@example.com`.
- Grafana `GET /api/health` returned 200. Prometheus `GET /api/v1/targets` returned 200.

The first live demo login failed because `demo@agentforge.local` is rejected by email validation. Demo addresses are now `@example.com`. The verification script above passed after that change.

## Limitations

- The worker is a Redis lease/queue process, not Celery. Behavior covered here is claim, delay, retry, dead letter, and crash recovery.
- Default LLM provider is the deterministic mock. The OpenAI path is implemented and unit-tested with a fake HTTP transport; this run did not call a paid provider.
- Access and refresh tokens are stored in `localStorage`.
- SSRF validation still has a small DNS time-of-check/time-of-use window for public hostnames.
- `npm audit` reports transitive frontend advisories. The production build was not force-upgraded, because that can change unrelated packages.
- Compose publishes the API port with `TRUST_PROXY=true` so the frontend can forward client IPs. Do not expose that port to untrusted networks without turning the flag off or terminating TLS at a trusted proxy.
- Demo passwords and the development JWT secret are local defaults. Production startup rejects them.
