# Fly.io deployment hygiene

Fly is a Docker-host platform with a few opinionated primitives (machines, volumes, secrets, internal networking). The deploy story is `fly deploy`, but the details matter.

## Dockerfile

Multi-stage build. Final image should be small (Distroless or `scratch`) and run as non-root.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/horrors ./cmd/horrors
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/migrate ./cmd/migrate

FROM gcr.io/distroless/static:nonroot
COPY --from=build /out/horrors /app/horrors
COPY --from=build /out/migrate /app/migrate
COPY --from=build /src/internal/db/migrations /app/migrations
USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/app/horrors"]
```

- `CGO_ENABLED=0` for static binary; works in distroless.
- `-trimpath` strips local paths from binary (smaller, less info leak).
- `-s -w` strips debug info (smaller binary). Trade-off: harder to debug in prod; usually worth it.
- Non-root user. Distroless `nonroot` is uid 65532.
- Ship migrations in the image so the release_command can run them.

## fly.toml

```toml
app = "persistent-horrors"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[deploy]
  release_command = "/app/migrate up"
  strategy = "rolling"

[env]
  PORT = "8080"
  LOG_LEVEL = "info"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = false  # we have always-on cron
  auto_start_machines = true
  min_machines_running = 1

  [[http_service.checks]]
    interval = "15s"
    timeout = "2s"
    grace_period = "10s"
    method = "GET"
    path = "/healthz"

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

- `release_command` runs migrations BEFORE new machines accept traffic. Migration failure halts the deploy.
- `auto_stop_machines = false` because we have always-on cron jobs. Don't let Fly stop the machine.
- `min_machines_running = 1` (or 2 for redundancy). Match what your cron leader-election expects.
- Health checks point at `/healthz` (process alive). Don't gate on DB connectivity in `/healthz` or transient DB issues take traffic offline; use `/readyz` for that if needed.

## Secrets

```bash
fly secrets set DATABASE_URL='postgres://...'
fly secrets set APNS_KEY_P8="$(cat AuthKey_XXX.p8)"
fly secrets set APNS_KEY_ID='XXXXXXXXXX'
fly secrets set APNS_TEAM_ID='XXXXXXXXXX'
fly secrets set APPLE_BUNDLE_ID='com.apocryphalenterprises.PersistentHorrors'
fly secrets set SESSION_SIGNING_KEY="$(openssl rand -base64 32)"
fly secrets set ADMIN_ALLOWLIST_SUBS='001234.abc...,001234.def...'
```

- Setting a secret triggers a deploy by default (machines restart with the new env). Use `--stage` to batch and deploy once.
- Secrets are write-only via the API; you can't read them back. Store the source of truth in a password manager.
- Rotate signing keys regularly (every 6–12 months); old sessions invalidate at next request.

## Migrations strategy

- Migrations run as `release_command` during deploy.
- A failed migration halts deploy — old machines keep serving with old schema. Good.
- For migrations that can't run in a transaction (CREATE INDEX CONCURRENTLY), guard with `BEGIN/COMMIT` boundaries appropriately and run as a separate file.
- For destructive migrations (DROP COLUMN), do it in two deploys: deploy code that no longer reads the column, then deploy the migration. Never combine.

## Postgres on Fly

- Fly Postgres MPG (Managed Postgres) is the option to use. The legacy "Fly Postgres" (Stolon-based) is deprecated.
- Pick a region matching your app (`iad`).
- Connect via the internal `.flycast` address: `postgres://...@<app>.flycast:5432/<db>`. This avoids egress and TLS overhead.
- For dev cluster, the smallest tier is fine. Scale up when load justifies.
- Backups: Fly Postgres takes daily snapshots automatically. Validate restore monthly (untested backups are fiction).

## Networking

- HTTP traffic comes through Fly's edge (Anycast) and lands on your machines via the `internal_port`.
- TLS is terminated at the edge. Inside the network it's plain HTTP.
- For service-to-service inside Fly, use `<app>.internal` DNS (regional) or `<app>.flycast` (geographic anycast within Fly).

## Multi-machine considerations

- Multiple machines means multiple cron firings. Use `pg_try_advisory_lock` for leader election.
- Multiple machines also means HTTP redundancy — clients won't notice a single machine restart.
- For state that genuinely requires singleton (e.g., a state-machine for pending pushes), back it with Postgres rows + advisory locks rather than in-process state.

## Observability on Fly

- `fly logs` streams stderr/stdout. Use JSON slog so it parses cleanly.
- `fly dashboard` has CPU/memory metrics built in. For app-specific metrics, expose `/metrics` and scrape with an external Prometheus or Grafana Cloud.
- For incidents, `fly ssh console` to get a shell on a machine. Distroless has no shell — keep a `debug` build profile that uses `gcr.io/distroless/base-debian12:debug` if you actually need this; otherwise debug remotely.

## Cost watching

- Fly bills per machine-second + storage + egress. Two `shared-cpu-1x@512MB` machines + dev Postgres ≈ $15–25/mo.
- Set up billing alerts in Fly's dashboard. Surprise bills happen.

## Don't

- Don't deploy with `--strategy immediate` unless you really mean "drop existing connections instantly."
- Don't put migrations behind a feature flag. Run them as `release_command` and let deploy fail if they fail.
- Don't bake secrets into the image. The image goes to Fly's registry and to anywhere you run it locally.
- Don't run as root. Distroless `nonroot` user is good default.
- Don't use Fly Postgres v1 / Stolon. Migrate to MPG if you're on it.
