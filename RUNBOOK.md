# AgentForge runbook

## What healthy looks like

- `GET /health` returns `200` even when dependencies are down. It only proves the API process is up.
- `GET /ready` returns `200` when PostgreSQL and Redis both answer. `503` means a dependency is unavailable.
- The worker logs `agentforge worker started` and refreshes `agentforge:worker:<id>` in Redis.
- A new task moves `pending` or `queued` to `running`, then to a terminal status. The terminal row, steps, and any stored records are in PostgreSQL.

## Where to look

```bash
docker compose ps
docker compose logs api --tail 100
docker compose logs worker --tail 100
docker compose logs postgres --tail 50
docker compose logs redis --tail 50
```

API and worker logs are JSON on stdout: `ts`, `level`, `logger`, `message`.

Prometheus scrapes `api:8000/metrics` and `worker:9100/metrics`. Grafana is at port 3000, folder **AgentForge**.

## Task stuck in queued

1. Confirm the worker container is running and can reach Redis and PostgreSQL.
2. Check `agentforge_queue_depth` and `LLEN agentforge:queue` in Redis.
3. The worker promotes due retries from the `agentforge:delayed` sorted set and reconciles orphaned `pending` / `queued` rows. A crashed worker should be restarted with `docker compose restart worker`; the next loop requeues expired leases.
4. If Redis lost the queue entry but the row is still `queued`, the reconciler pushes it again. Duplicate queue entries are safe: the claim update allows only one worker to own the row.

## Task stuck in running

The worker holds a lease for the agent's timeout. If the process dies, `lease_expires_at` passes and another loop sets the task back to `queued` without counting a failed attempt. If the same worker is alive but wedged, restart it. The old claim token will no longer match, so the stale execution stops instead of overwriting the new one.

## Task failed immediately

Open the execution in the dashboard or `GET /api/v1/tasks/{id}`.

- `Address is not allowed` or `Host is not allowed`: the HTTP tool blocked a private, loopback, link-local, or metadata target. Use a public `http` or `https` URL.
- `Tool '...' is not allowed`: the model selected a tool the agent does not have, or a tool outside the allowlist.
- `LLM API key is not configured`: the agent provider is `openai` and `LLM_API_KEY` is empty. Use `mock` for local runs.
- `Simulated transient LLM failure`: the task input set `simulate_transient_failures`. That hook is ignored when `ENVIRONMENT=production`.

Retries use exponential backoff from `RETRY_BASE_SECONDS` up to `RETRY_MAX_SECONDS`. When `attempt` exceeds `max_retries`, the task is marked `failed`, `dead_letter=true`, and a row is added to `dead_letters`. `POST /api/v1/tasks/{id}/retry` clears that state and queues the same task again.

## Duplicate work

Creating a task with the same owner and idempotency key returns the existing row and sets `Idempotency-Replayed: true`. The database unique constraint is the source of truth. A second queue copy of the same task id does not run the tools twice, because the claim is conditional on status.

## Authentication failures

- `401` on login: email or password does not match, or the user is inactive.
- `401` on other routes: the access token is missing, expired, or is a refresh token.
- Refresh tokens are one-time. If a refresh fails, sign in again.
- `429` includes `Retry-After: 60`. Task creation has a tighter limit than general API calls.

## Database or Redis is down

- Readiness goes `503`.
- Task creation returns `503` if Redis cannot accept the queue push. The row stays `pending`. Retry the same idempotency key after Redis recovers; the API will queue that pending task.
- The API can still read PostgreSQL when Redis is down, but login cannot store a refresh token.
- The worker waits during startup until the `users` table exists, so it can boot before the API finishes migrations and then retry.

## Migrations

The API container runs `alembic upgrade head` before serving traffic. To run it yourself from `backend` against a reachable database:

```bash
alembic upgrade head
python -m app.seed
```

Do not point `DATABASE_URL` at a production database from a laptop unless that is intentional. The migration creates users, agents, tasks, task steps, activity, stored records, and dead letters.

## Demo seed did not appear

`SEED_DEMO` must be true and `ENVIRONMENT` must not be `production`. Default demo passwords are refused in production. Seed is idempotent: it will not create a second demo task with the key `seed-demo-urgent-login`.

## SSE looks frozen

The event stream polls PostgreSQL and Redis and closes after a terminal status or about 120 seconds. The execution page falls back to a direct `GET` if the stream ends. Confirm the response is not being buffered by a proxy. The Compose nginx config sets `proxy_buffering off` and `X-Accel-Buffering: no`.

## Reset local data

```bash
docker compose down -v
docker compose up --build
```

`-v` deletes the Postgres volume, including users, agents, and execution history.
