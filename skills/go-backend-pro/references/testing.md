# Testing

Tests that pass while the code is wrong are worse than no tests. Aim for tests that fail loudly when the code regresses.

## Table-driven tests

The default pattern for unit tests:

```go
func TestParseBulletinDate(t *testing.T) {
    cases := []struct {
        name    string
        input   string
        want    time.Time
        wantErr bool
    }{
        {"valid date", "2026-04-29", time.Date(2026, 4, 29, 0, 0, 0, 0, time.UTC), false},
        {"empty", "", time.Time{}, true},
        {"timezone suffix rejected", "2026-04-29T00:00:00Z", time.Time{}, true},
    }
    for _, tc := range cases {
        t.Run(tc.name, func(t *testing.T) {
            got, err := ParseBulletinDate(tc.input)
            if (err != nil) != tc.wantErr {
                t.Fatalf("err = %v, wantErr = %v", err, tc.wantErr)
            }
            if !tc.wantErr && !got.Equal(tc.want) {
                t.Errorf("got %v, want %v", got, tc.want)
            }
        })
    }
}
```

- Each row gets a `name` for `t.Run`. Failures localize to one row.
- Closure variables (`tc`) are captured per iteration in Go 1.22+.
- Prefer `t.Fatalf` for setup failures, `t.Errorf` to allow remaining assertions.

## httptest

Test handlers without binding a real port:

```go
func TestVoteHandler(t *testing.T) {
    db := newTestDB(t)
    h := api.NewHandler(db, testLogger())
    body := `{"date":"2026-04-29","concur":true}`
    req := httptest.NewRequest("POST", "/v1/votes", strings.NewReader(body))
    req.Header.Set("Authorization", "Bearer "+testSession(t, db))
    w := httptest.NewRecorder()
    h.ServeHTTP(w, req)

    if w.Code != http.StatusOK {
        t.Fatalf("status %d, body %s", w.Code, w.Body.String())
    }
    // ... assert response shape
}
```

- Use `httptest.NewRecorder` for in-memory; use `httptest.NewServer` only when you need a real port (rare).
- Build request bodies with `strings.NewReader` for simple cases; use a typed struct + `json.Marshal` when the body is non-trivial.

## Database integration tests

- Spin up a real Postgres for integration tests. Don't mock the DB; mocks lie about SQL semantics, transactions, and indexes.
- Use `testcontainers-go` to launch ephemeral Postgres per test package. Or run `docker compose` once and have tests `TRUNCATE` between cases.
- Run migrations in `TestMain` so the schema is fresh.
- Each test gets a clean DB state via `t.Cleanup` truncating affected tables, OR each test runs in a transaction that's rolled back at end.

```go
func newTestDB(t *testing.T) *pgxpool.Pool {
    t.Helper()
    pool, err := pgxpool.New(ctx, testDatabaseURL)
    if err != nil { t.Fatalf("connect: %v", err) }
    t.Cleanup(func() {
        _, _ = pool.Exec(ctx, "TRUNCATE bulletins, votes, users CASCADE")
        pool.Close()
    })
    return pool
}
```

## Mocks vs fakes vs real

- Real services where feasible (DB, your own HTTP server). Catches the most bugs.
- Fakes (in-memory implementation conforming to the interface) for things you can't run locally easily (third-party APIs).
- Mocks (recorded expectations) sparingly. They make tests brittle to refactor.
- For APNs and Apple JWKS in tests, use a fake server (`httptest.NewServer`) returning canned responses.

## Concurrency tests

- Always run with `-race` in CI: `go test -race ./...`.
- Race detector adds ~5x cost but catches data races deterministically.
- For deterministic tests of concurrent code, inject a clock (don't call `time.Now()` directly) and gate test progression on channels rather than `time.Sleep`.

## Goroutine leak detection

- `go.uber.org/goleak.VerifyNone(t)` at the end of significant tests catches goroutines still running.
- Place in `TestMain` to enforce process-wide.

## Golden files

- For tests of complex output (JSON responses, rendered templates, generated SQL), compare against golden files.
- `-update` flag pattern: `go test -update` regenerates golden files; default run compares.
- Diff with `cmp` package or `github.com/google/go-cmp/cmp` for structured diffs.

## Test naming

- `TestXxx` for table-driven units.
- `TestXxx_BoundaryCondition` when a single behavior needs its own test.
- Subtest names describe behavior, not numbers (`"empty input"`, not `"case 1"`).

## Test coverage

- 100% coverage is meaningless. Aim for "every reachable error path is exercised at least once."
- Coverage report (`go test -cover`) flags untested branches; use it to find blind spots, not as a target metric.
- Skip coverage for `main()` and trivial constructors. Cover business logic, validation, and error handling.

## Build tags

- Slow integration tests behind `//go:build integration` so `go test ./...` runs the unit suite quickly.
- CI runs `go test -tags integration ./...` separately.
- E2E that hits real Apple / real APNs (rare) behind `//go:build e2e`.

## Don't

- Don't test through the database for pure logic tests. Pull the logic out and test it in isolation.
- Don't share test state across cases. Every test gets its own setup; use `t.Cleanup`.
- Don't use `time.Sleep` to coordinate goroutines. Flaky.
- Don't catch and silently ignore errors in tests. Surface them with `t.Fatal`.
- Don't write tests that assert against generated values (UUIDs, timestamps) verbatim. Compare structurally with `cmpopts.IgnoreFields` or by type/range.
