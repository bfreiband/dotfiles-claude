# HTTP server patterns

Use `net/http` directly when the routing is simple. Reach for `chi` (or similar) only when you need URL params, sub-routers, or middleware composition that gets awkward with `http.ServeMux` patterns.

## Server setup

- Always set timeouts: `ReadTimeout`, `ReadHeaderTimeout`, `WriteTimeout`, `IdleTimeout`. Defaults are zero (unlimited) — slowloris-vulnerable.
- Use `http.Server{}` directly. Don't use `http.ListenAndServe()` in production code — it gives you no Server reference for graceful shutdown.
- Implement graceful shutdown: catch SIGTERM, call `srv.Shutdown(ctx)` with a 30s timeout.
- Use `errgroup` to run HTTP server, scheduler, and worker pool from `main()` and exit cleanly when any returns an error.

```go
srv := &http.Server{
    Addr:              ":8080",
    Handler:           h,
    ReadTimeout:       10 * time.Second,
    ReadHeaderTimeout: 5 * time.Second,
    WriteTimeout:      30 * time.Second,
    IdleTimeout:       120 * time.Second,
}
```

## Handler signature

- Stick to `http.HandlerFunc` (`func(w, r)`). Avoid bespoke handler types unless you need `error` returns + central error rendering — then the wrapper is a thin shim.
- Return after `http.Error` or `WriteHeader` — don't keep writing.
- Set `Content-Type` BEFORE `WriteHeader`. Headers after the first write are dropped (or panic in some configs).
- Set `Content-Type: application/json; charset=utf-8` for JSON responses.

## Request body

- ALWAYS limit body size: `r.Body = http.MaxBytesReader(w, r.Body, 1<<20)` (1 MiB default; tune per endpoint).
- Use `json.NewDecoder(r.Body)` with `dec.DisallowUnknownFields()` for write endpoints. Unknown-field rejection catches client bugs early.
- Validate the decoded struct before using it. Don't trust client-supplied IDs for authorization decisions.
- Close request body? Not necessary — the http package does it. But draining (`io.Copy(io.Discard, r.Body)`) before returning keeps the connection reusable.

## JSON encoding

- Use `json.NewEncoder(w).Encode(value)` rather than `json.Marshal` + `w.Write` — streams without buffering the full output.
- Define explicit response types per endpoint. Don't return DB rows directly — they often have fields the client shouldn't see (`password_hash`, internal IDs).
- Use `json:"fieldName,omitempty"` for optional fields. Time zero values are NOT omitted by `omitempty` — use a pointer if needed.
- Custom `MarshalJSON` only when stdlib tags are insufficient.

## Status codes

- 200 — successful read or update with response body.
- 201 — successful creation; include `Location` header pointing to the new resource.
- 204 — successful operation with no response body.
- 400 — malformed request (bad JSON, missing required field, validation failure).
- 401 — missing or invalid auth credentials.
- 403 — auth valid but caller not allowed.
- 404 — resource doesn't exist (or caller can't see it; don't distinguish for security).
- 409 — conflict (concurrent update, duplicate creation).
- 422 — semantic validation failure (request was syntactically valid).
- 429 — rate-limited.
- 500 — unhandled server error. Don't include stack traces or DB errors in the response body.

## Error responses

- Use a consistent envelope: `{"error":{"code":"INVALID_VOTE","message":"..."}}`. Pick a shape and stick with it across all endpoints.
- Never leak internal error strings to clients. Log the wrapped error server-side; return a stable code + safe message.
- Include a request ID in error responses (and in logs). The client can quote it when reporting bugs.

## Middleware

- Compose middleware as `func(http.Handler) http.Handler`. Standard pattern; no framework needed.
- Order matters: recovery → request-id → logging → auth → rate-limit → handler.
- Recovery middleware is mandatory. Without it, a panic in any handler crashes the process.
- Pass per-request data via `context.WithValue`. Define a typed context key (`type ctxKey int`) — don't use string keys.

## Graceful shutdown

```go
ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
defer stop()

go func() {
    if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
        log.Error("server failed", "err", err)
    }
}()

<-ctx.Done()
shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
defer cancel()
if err := srv.Shutdown(shutdownCtx); err != nil {
    log.Error("graceful shutdown failed", "err", err)
}
```

## REST conventions

- Version in the path: `/v1/...`. Bump only on breaking changes.
- Plural collection names: `/v1/bulletins`, not `/v1/bulletin`.
- Use HTTP verbs correctly: GET is safe + idempotent (no side effects), PUT is idempotent (same call multiple times = same state), POST is neither.
- Date-only path segments use ISO 8601: `/v1/bulletins/2026-04-29`.
- Pagination: `?limit=50&cursor=...`. Don't use offsets for large tables; cursor-based scales.

## Caching

- Compute and return `ETag` for cacheable responses. Honor `If-None-Match`: return 304 without body.
- Set `Cache-Control: public, max-age=60` for content that's broadly cacheable (today's bulletin, after publish).
- Vary responses by relevant headers (`Vary: Authorization` for auth-gated endpoints).
