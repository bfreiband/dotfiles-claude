# Postgres usage

Default to `pgx/v5` for new code. Use `pgxpool.Pool` for the connection pool. `database/sql` is acceptable when you need its driver-agnostic interface, but `pgx` directly is preferred for Postgres-only code (faster, richer type support).

## Connection pool

- One `*pgxpool.Pool` per process, created in `main()`, passed into constructors.
- Tune `MaxConns` based on the actual machine and DB. For a 512MB Fly machine, 5–10 is usually right. Don't blindly use 100.
- Set `MaxConnLifetime: 30 * time.Minute` and `MaxConnIdleTime: 5 * time.Minute` so stale connections are recycled.
- Always `defer pool.Close()` in main.

## Queries

- ALL queries are parameterized. `$1`, `$2` placeholders. Never `fmt.Sprintf` a value into SQL.
- Use `pool.QueryRow(ctx, sql, args...)` for single-row reads, `pool.Query(ctx, sql, args...)` for multi-row.
- Pass `ctx` to every query call. Cancellation propagates to the DB driver.
- Define queries as package-level constants, sqlc-generated, or in dedicated `.sql` files. Don't sprinkle SQL through handlers.

## Transactions

```go
tx, err := pool.Begin(ctx)
if err != nil { return fmt.Errorf("begin: %w", err) }
defer tx.Rollback(ctx) // safe to call after Commit; pgx returns ErrTxClosed which we ignore

// ... operations on tx ...

if err := tx.Commit(ctx); err != nil {
    return fmt.Errorf("commit: %w", err)
}
```

- `defer tx.Rollback()` immediately after `Begin`. Commit at the success path. Rollback after Commit is a no-op; this guarantees rollback on any panic or early return.
- Keep transactions short. Don't hold one across an external API call.
- Use `pgx.BeginTxFunc` (or write your own helper) when you want a clean closure-based pattern.

## Time zones

- All timestamp columns are `timestamptz`. Never use `timestamp` (without time zone) — it's a footgun.
- `time.Now()` returns UTC in Go (well, the local time zone, but stored as UTC offset). Postgres receives it correctly via `pgx`.
- "Today" / calendar-date logic must name a time zone explicitly:
  ```sql
  WHERE bulletin_date = (current_timestamp AT TIME ZONE 'America/New_York')::date
  ```
- Store calendar dates as `date` (not `timestamp`). Don't mix.
- When formatting a time for a client, decide the time zone at the boundary; don't assume UTC == display.

## Indexes

- Add an index when a query plan shows a sequential scan on a table that will grow.
- Composite indexes follow a left-prefix rule: `(a, b, c)` serves queries on `a`, `(a,b)`, `(a,b,c)` — not on `b` alone.
- **Partial indexes** for sparse predicates: `CREATE INDEX ... WHERE published_at IS NOT NULL`. Smaller, faster.
- Covering indexes (`INCLUDE`) avoid heap visits for read-only queries.
- Run `EXPLAIN (ANALYZE, BUFFERS)` on any query that touches a table > 10k rows before merging.
- Don't over-index write-heavy tables; each index is a write tax.

## Upserts

```sql
INSERT INTO users (apple_subject, email)
VALUES ($1, $2)
ON CONFLICT (apple_subject) DO UPDATE
  SET last_seen_at = now()
RETURNING id;
```

- Always use `ON CONFLICT` for "create or update" semantics. Don't `SELECT` then `INSERT` — race condition.
- `RETURNING` lets you get the id without a second query.
- For full-list-replace patterns (e.g., user mitigations), wrap `DELETE` + bulk `INSERT` in a transaction.

## Advisory locks

- `pg_try_advisory_lock(<int64>)` is non-blocking; returns false if held. Use this for leader election among multiple machines running the same cron.
- `pg_advisory_lock(<int64>)` blocks; use only when blocking is actually wanted.
- Locks released by `pg_advisory_unlock` OR by session end. For session-end semantics, `SELECT pg_try_advisory_lock(...)` on a dedicated connection — do not use the pool.
- Pick a stable, namespaced int64 for each lock (hash a string with `hash/fnv` if needed).

## Migrations

- Use `golang-migrate` or `goose`. Migrations are checked into the repo as numbered SQL files.
- `0001_init.sql`, `0002_add_votes.sql`, etc. Up + down. Down is best-effort but write it.
- Each migration is a single transaction (most tools do this automatically). Operations that can't run in a transaction (CREATE INDEX CONCURRENTLY) need a separate file.
- Run migrations as part of deploy (`fly deploy` `release_command = "/app/migrate up"`), not at request time.
- Never edit a merged migration. Add a new one.

## Pgx-specific

- `pgx.QueryRow().Scan(&val)` for single rows. `errors.Is(err, pgx.ErrNoRows)` for not-found.
- `pgx.RowToStructByName[T]` for clean row-to-struct mapping (uses `db:"col_name"` tags).
- `Batch` for sending multiple statements in one round trip. Useful for bulk inserts.
- Type registration for custom Postgres types (enums, arrays of custom types) via `pool.Config().AfterConnect`.

## Sqlc (recommended for non-trivial query sets)

- Write SQL in `queries.sql` with annotations (`-- name: GetUser :one`). Sqlc generates typed Go.
- Type safety wins over hand-rolled scanning. No reflect, no scan errors at runtime for typos.
- Mix freely: complex generated queries + ad-hoc `pool.Exec` for migrations or one-offs.

## Don't

- Don't use ORMs (`gorm`, `ent`). They obscure the SQL and make performance debugging harder.
- Don't use `database/sql` placeholders (`?`) — Postgres uses `$1`, `$2`. Mixing breaks.
- Don't catch `sql.ErrNoRows` and silently return zero values. Return a typed not-found error so the handler can render 404.
