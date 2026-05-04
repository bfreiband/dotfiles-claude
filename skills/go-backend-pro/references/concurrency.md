# Concurrency

Go's superpower; also where most bugs live.

## Context propagation

- Every goroutine doing I/O has a context. Pass it as the first argument.
- A goroutine launched from a request handler that needs to outlive the request must use `context.WithoutCancel(r.Context())`. Otherwise it dies when the response is written.
- A goroutine launched at startup (background workers, schedulers) takes a service-scoped context that's cancelled at shutdown.
- Never spawn a goroutine that has no path to be cancelled. That's a leak. Either `select` on `ctx.Done()` or have a definite finite work item.

## Worker pools

For fan-out work like APNs push delivery:

```go
const workers = 16
jobs := make(chan deviceToken, 256)
var g errgroup.Group

for range workers {
    g.Go(func() error {
        for tok := range jobs {
            if err := sendOne(ctx, tok); err != nil {
                slog.Error("apns send", "token_prefix", tok[:8], "err", err)
                // continue; one failure shouldn't kill the worker
            }
        }
        return nil
    })
}

// producer
for tok := range tokens {
    select {
    case jobs <- tok:
    case <-ctx.Done():
        close(jobs)
        return ctx.Err()
    }
}
close(jobs)
return g.Wait()
```

- Bounded workers (`const workers = N`) — don't spawn one goroutine per item.
- Buffered channel sized to absorb short producer/consumer mismatches.
- Producer closes the channel when done. Workers `range` over it and exit naturally.
- `errgroup` for managing the worker group. `g.Go` captures errors; `g.Wait` returns the first one.

## errgroup

- `golang.org/x/sync/errgroup` is the right tool for "run N things, fail if any fail."
- `g.SetLimit(N)` to bound concurrency.
- Pass an `errgroup.WithContext` so failures cancel siblings.
- For independent jobs that should NOT cancel each other on failure, use a plain `sync.WaitGroup` + collect errors with `errors.Join`.

## Channels

- Buffer size matters. Unbuffered = synchronous handoff (good when you want backpressure). Buffered = async, can hide deadlocks.
- Don't send on a closed channel — it panics. Senders close, receivers don't.
- Closing a nil channel panics. Sending on a nil channel blocks forever. Use this intentionally (e.g., disable a select case by setting it to nil).
- Prefer one-direction channel parameters: `func consume(ch <-chan T)`. The compiler enforces who sends and who receives.
- For "signal" channels (just notify, no data), use `chan struct{}`. Zero memory.

## Sync primitives

- `sync.Mutex` — guard a single resource. Lock + immediate `defer unlock()`.
- `sync.RWMutex` — only when reads vastly outnumber writes AND writes are non-trivial. Otherwise plain Mutex.
- `sync.Once` — one-shot initialization. Common for lazy singletons (JWKS cache).
- `sync.Map` — only for "many goroutines reading and writing disjoint keys" workloads (e.g., per-connection state). For typical use, `map` + `Mutex` is faster and simpler.
- `atomic` — counters, flags, but only when the protocol is genuinely simple. Anything more complex than load/store/CAS belongs behind a Mutex.
- `singleflight.Group` (`golang.org/x/sync/singleflight`) — collapse duplicate concurrent requests for the same key. Perfect for JWKS refresh.

## Goroutine lifecycle

- Every goroutine has an owner. Document who waits for it (or design so the goroutine is fire-and-forget with a definite finite lifetime).
- Test for leaks: use `goleak.VerifyNone(t)` in significant tests. It catches goroutines still running at test end.
- Long-running goroutines log when they start and stop. Helps debugging in prod.

## Common bugs

- **Loop variable capture (pre-1.22)**: `for _, item := range items { go func() { use(item) }() }` captures the same variable. Fixed in Go 1.22+ but watch for older code or odd toolchain configs.
- **Goroutine leak via blocked channel send**: producer sends on a channel whose consumer has returned. Always pair sends with `select { case ch <- x: case <-ctx.Done(): }`.
- **WaitGroup misuse**: `wg.Add(1)` inside the goroutine — race with `wg.Wait`. Always `Add` before `go`.
- **Shared map without sync**: read + write from goroutines without a mutex. `go test -race` catches it; trust the race detector.
- **Defer in a loop**: `for x := range items { f, _ := os.Open(...); defer f.Close() }` — none close until the function returns. Use an inner function or explicit Close.

## Testing concurrent code

- Always run tests with `-race` in CI. Race detector adds ~5x cost but catches data races deterministically.
- For deterministic ordering, inject a clock (`clockwork`, your own interface) rather than calling `time.Now()` directly.
- For deterministic concurrency, use channels to gate test progression rather than `time.Sleep`.

## Don't

- Don't reach for goroutines speculatively to "make it faster." Profile first; concurrency adds bugs.
- Don't `runtime.LockOSThread` unless you genuinely need it (Cgo callbacks, syscalls that require a specific thread). It's almost never the answer.
- Don't share unsynchronized state across goroutines. The race detector finds it; production users find it less politely.
