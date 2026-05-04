# Hotspots — scan for these first

Run a quick first pass for these dangerous patterns before any deeper review. Each is a high-signal defect indicator.

## Errors and panics

- A handler or goroutine returns/swallows `err` without wrapping or logging.
- A `panic` outside `main()` startup misconfiguration. (Recovery middleware should exist; panics inside handlers without recovery crash the process.)
- `_ = err` or `if err != nil { return }` where the caller now has no idea what failed.
- Sentinel errors checked with `==` instead of `errors.Is`. Type assertions instead of `errors.As`.

## Concurrency

- A `go func()` launched from a request handler that uses `r.Context()`. The goroutine dies when the response is written. Use `context.WithoutCancel(r.Context())`.
- A goroutine with no clear stop condition (`for { ... }` without a `select` on a context or stop channel). This is a leak.
- A shared map / slice mutated from multiple goroutines without a mutex.
- `sync.WaitGroup.Add` called inside the goroutine instead of before launch — race on Wait.
- A channel send/receive that can deadlock if the consumer is gone.

## SQL and data

- String interpolation or `fmt.Sprintf` building a query. Always parameterize.
- A query inside a loop (N+1). Prefer one query that joins or `IN` lists.
- A transaction without `defer tx.Rollback()` — a panic or early return leaks an open transaction.
- `time.Now()` used as a calendar date without converting to a named time zone.
- A `timestamptz` compared against a `time.Time` without thinking about UTC vs local.
- An `INSERT` with a hand-built unique check (`SELECT WHERE id = ?` then `INSERT`) instead of `ON CONFLICT`.

## HTTP

- A handler that calls `io.ReadAll(r.Body)` without `http.MaxBytesReader` first. Unbounded body.
- An HTTP server with no `ReadTimeout` / `WriteTimeout` / `IdleTimeout`. Slowloris vulnerable.
- A handler that calls `http.Error` after already writing a body or status. Header-after-write panic.
- JSON decoded with `json.Decoder` but `DisallowUnknownFields` is not set on a write endpoint accepting strict input.
- A 200 OK on a write endpoint that didn't actually verify the operation succeeded.

## Secrets and logging

- A secret (API key, session token, APNs `.p8`, JWT) appears in a log line, error string, or test fixture as anything other than an obvious dummy.
- A token compared with `==` rather than `subtle.ConstantTimeCompare` for auth.
- A debug print left in (`fmt.Println`, `log.Println` outside slog).

## Configuration

- A default value for a secret env var (`os.Getenv("X")` returning empty, then proceeding). Should fail fast.
- Hardcoded URLs to production services (`https://api.push.apple.com`) — fine if intentional, but should be configurable for sandbox vs prod.

## Tests

- Tests that share global state across cases without `t.Cleanup`.
- DB tests that don't reset between cases.
- Tests that hit the network (real SIWA, real APNs) without a build tag or integration-only marker.

When any of these fire, prioritize them in the review output. They're nearly always real defects, not style preferences.
