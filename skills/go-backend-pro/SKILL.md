---
name: go-backend-pro
description: Reviews Go backend code for idiomatic style, HTTP server hygiene, Postgres correctness, concurrency safety, and common server-side pitfalls. Use when reading, writing, or reviewing Go backend code.
license: MIT
metadata:
  version: "1.0"
---

Review Go backend code for correctness, idiomatic style, and adherence to server-side conventions. Report only genuine problems — do not nitpick or invent issues.

Review process:

1. Scan for known-dangerous patterns using `references/hotspots.md` to prioritize what to inspect.
1. Validate Go language idioms using `references/go-idioms.md` (errors, contexts, package layout, naming).
1. Validate HTTP server patterns using `references/http.md` (handlers, middleware, JSON, status codes, timeouts, graceful shutdown).
1. Validate Postgres usage using `references/postgres.md` (pgx, transactions, parameterized queries, time zones, indexes, advisory locks).
1. Validate concurrency using `references/concurrency.md` (context propagation, goroutine leaks, worker pools, errgroup).
1. Validate observability using `references/observability.md` (slog, request IDs, error wrapping, metrics surface).
1. Validate security using `references/security.md` (input validation at the boundary, JWT pitfalls, secrets handling, rate limiting).
1. Validate configuration using `references/configuration.md` (env vars, fail-fast, no secret defaults).
1. Validate testing using `references/testing.md` (table-driven, httptest, DB integration patterns).
1. Validate deployment hygiene using `references/deploy-fly.md` (Dockerfile, fly.toml, migrations as release_command, secrets).

If doing a partial review, load only the relevant reference files.

## Core Instructions

- Target Go 1.22 or later. Use `slog`, `errors.Is/As`, `errors.Join`, `range over int`, `cmp` package where appropriate.
- `context.Context` is the first parameter on any function that does I/O or can be cancelled. Never store contexts in structs.
- All errors that cross a function boundary are wrapped with `fmt.Errorf("doing X: %w", err)`. Never return a bare `err` from a deep call site.
- Never `panic` in request handlers, scheduled jobs, or any goroutine-launched code. Recover at the top level (middleware) and log; never let a panic crash the process during request handling. `panic` is acceptable only at startup for unrecoverable misconfiguration.
- All SQL is parameterized. String-concatenated queries are a security defect, not a style issue.
- All times stored in Postgres are `timestamptz`. All "today" / "calendar date" logic explicitly names a time zone (`AT TIME ZONE 'America/New_York'`); `time.Now()` is UTC and must be converted at the boundary.
- HTTP handlers always set a request body size limit (`http.MaxBytesReader`) and a request timeout. Never read an unbounded body.
- Goroutines launched from request handlers must derive from a context that outlives the request (typically `context.WithoutCancel(r.Context())` or a service-scoped context), or they get cancelled when the response returns. Goroutines without a clear stop condition are a leak.
- Secrets come from environment variables only. They never appear in code, log lines, error messages, or commits. `*_test.go` fixtures use obvious dummies.
- Prefer the standard library. `net/http`, `database/sql` or `pgx`, `encoding/json`, `log/slog`, `context`, `errors`. Reach for third-party only when the stdlib is genuinely insufficient (`pgx`, `golang-migrate`, a router like `chi` if `http.ServeMux` patterns are awkward, `go-jose` for JWT, `golang.org/x/sync/errgroup`).
- Do not introduce ORMs (`gorm`, `ent`). Use `sqlc` for generated typed queries or hand-rolled `pgx` calls.
- Do not introduce dependency-injection frameworks (`wire`, `dig`). Pass dependencies as constructor arguments.
- Do not log secrets, raw session tokens, raw APNs tokens, or full SIWA identity tokens. Hash or truncate before logging if needed for debugging.
- **Avoid one- and two-letter variable, parameter, and receiver names.** Prefer descriptive identifiers (`server`, `pool`, `verifier`, `request`, `response`, `index`, `match`, `user`). The narrow allowed exceptions are: `ctx context.Context`, `err error`, and `tx pgx.Tx` (because these are universal Go idioms). Single-letter receivers like `s *Server` are not allowed; use `server *Server`. Single-letter loop indexes like `i` are not allowed; use `index` or a domain-specific name. Two-letter helper variables like `tp`, `kv`, `wr` are not allowed; spell them out. This rule exists because two-character grep targets are noise and short names hurt readability under code review. The standard `(w http.ResponseWriter, r *http.Request)` is **not** an exception — use `(writer http.ResponseWriter, request *http.Request)`.

## Output Format

Organize findings by file. For each issue:

1. State the file and relevant line(s).
2. Name the rule being violated.
3. Show a brief before/after code fix.

Skip files with no issues. End with a prioritized summary of the most impactful changes.

Example output:

### internal/api/votes.go

**Line 42: Unparameterized SQL — string interpolation.**

```go
// Before
q := fmt.Sprintf("SELECT * FROM votes WHERE user_id = '%s'", userID)
rows, err := db.Query(ctx, q)

// After
rows, err := db.Query(ctx, `SELECT * FROM votes WHERE user_id = $1`, userID)
```

**Line 78: Goroutine launched from handler with request-scoped context — cancelled on response.**

```go
// Before
go recordMetric(r.Context(), "vote_cast")

// After — detached but still cancellable on shutdown
go recordMetric(context.WithoutCancel(r.Context()), "vote_cast")
```
