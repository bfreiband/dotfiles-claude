# Observability

A backend you can't see into is a backend you can't debug. The minimum viable observability surface is structured logs + request IDs + a few well-chosen counters.

## Structured logging with slog

Go 1.21+ ships `log/slog`. Use it. Don't add zap/zerolog/logrus unless there's a specific reason.

```go
logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
    Level: slog.LevelInfo,
    AddSource: false, // true in dev, false in prod
}))
slog.SetDefault(logger)
```

- JSON in production (machine-parseable). Text handler in dev (human-readable).
- Set the level from env (`LOG_LEVEL=debug|info|warn|error`).
- `slog.With("key", value)` returns a logger with persistent fields. Use it to bind request_id, user_id, etc. for the duration of a request.

## Logging conventions

- Log at the level that matches operational severity:
  - `Debug` — verbose tracing, off in prod by default.
  - `Info` — normal lifecycle (startup, shutdown, scheduled job ran, X items processed).
  - `Warn` — unexpected but recoverable (third-party slow, retry succeeded, deprecated path used).
  - `Error` — request failed, scheduled job failed, data integrity issue. Each Error log is something a human should triage.
- One log per failure. Don't log the same error at every layer of the call stack — wrap and log once at the boundary (HTTP handler middleware, scheduler tick).
- Include the wrapped error: `slog.Error("morning push", "err", err)`. The chain is preserved.
- Never log secrets. Never log full session tokens. If logging an APNs token for debugging, prefix only: `tok[:8]`.
- Don't log every successful request at Info; that's a metrics surface, not logs. Log unusual things.

## Request IDs

- Generate a request ID at the top of the middleware chain (`uuid.NewV7()` or `crypto/rand` 16 bytes hex).
- Inject into the context: `ctx = context.WithValue(ctx, requestIDKey, id)`.
- Bind to the per-request logger: `logger := slog.With("request_id", id)`.
- Echo back to the client in a `X-Request-Id` response header. Clients quote it when reporting bugs.
- Propagate to downstream calls (DB queries don't need it; outbound HTTP does — set as a header).

## Error wrapping for observability

- `fmt.Errorf("loading bulletin %s: %w", date, err)` makes the error message a breadcrumb chain.
- Errors have enough context that the FIRST log of them at the boundary is sufficient for debugging.
- Avoid `if err != nil { return errors.New("failed") }` — destroys the original.

## Metrics surface (when needed)

For v1, a small Prometheus surface covers most needs:

- `http_requests_total{method,route,status}` — counter
- `http_request_duration_seconds{method,route}` — histogram
- `db_query_duration_seconds{op}` — histogram
- `apns_push_total{status}` — counter (success / 410 / 429 / error)
- `scheduled_job_duration_seconds{job}` — histogram
- `scheduled_job_runs_total{job,result}` — counter

Use `github.com/prometheus/client_golang`. Expose `/metrics` on a separate port (typically 9090) so it's not exposed publicly via the same listener as the API.

For v0/MVP, you can defer Prometheus and rely on logs + Fly's built-in metrics. Add Prometheus when "what's slow?" becomes a recurring question.

## Distributed tracing

- For a single binary, tracing is overkill. Logs with request IDs cover it.
- If you eventually split services, OpenTelemetry is the standard. `go.opentelemetry.io/otel/sdk` + an exporter (Honeycomb, Tempo, etc.).
- Don't add OTel speculatively. The instrumentation surface is non-trivial.

## Error reporting

- For caught panics and 500-class errors, send to a centralized sink (Sentry, Honeybadger). Otherwise these errors die in logs and you don't notice.
- For a solo project, even a simple "post errors to a Slack webhook" sink beats nothing.
- Fingerprint by error chain (`errors.Unwrap` to root) so the same error doesn't generate hundreds of distinct alerts.

## Health endpoints

- `/healthz` — process is alive, returns 200 always (used by Fly health checks).
- `/readyz` — process can serve traffic. Checks DB connectivity. Returns 503 if dependencies are down. Used to gate traffic during startup or transient outage.
- Don't hide rich diagnostics behind these endpoints. They're for load balancers, not humans.

## Audit log

For compliance-sensitive operations (publish bulletin, send spike push, edit user data), write an audit row to a dedicated `audit_log` table or push to a structured log stream. Audit log is append-only; never updates or deletes. Include:

- Actor (user_id or "system")
- Action (`bulletin.publish`)
- Target (entity ID)
- Timestamp
- Source IP (if web) or job name (if scheduler)

Don't conflate audit logs with application logs. They serve different audiences.

## Don't

- Don't log at every function entry/exit. That's tracing, and slog isn't the right tool. If you need it, use OTel.
- Don't `fmt.Println` debug. Use `slog.Debug` and turn it off in prod.
- Don't catch errors and silently log them while still returning success. Either return the error or document explicitly why it's safe to ignore (rare).
