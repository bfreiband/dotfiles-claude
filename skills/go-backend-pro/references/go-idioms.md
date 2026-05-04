# Go language idioms

Target Go 1.22+. Reach for stdlib first.

## Errors

- Wrap with `fmt.Errorf("operation that failed: %w", err)`. The verb is `%w` (preserves the chain), not `%v`.
- Use `errors.Is(err, target)` for sentinels. Use `errors.As(err, &typedErr)` for typed errors. Never `==` or type assert.
- Define sentinels at package level: `var ErrNotFound = errors.New("entity not found")`.
- Define typed errors as structs implementing `Error() string` when callers need to extract structured data (status code, validation field).
- Use `errors.Join` to combine independent errors (parallel sub-task failures, batch validation).
- Do not log AND return the same error. Pick one. Return the wrapped error and let the call site (handler / scheduler) log once.
- Bare `return err` is a smell unless the function is a thin pass-through. Prefer `return fmt.Errorf("context: %w", err)`.

## Context

- `context.Context` is the first parameter, conventionally named `ctx`.
- Never store a context in a struct field. Pass it explicitly.
- Never pass `nil` for a context. Use `context.TODO()` if you genuinely don't have one yet, `context.Background()` only at process roots.
- Derive child contexts: `ctx, cancel := context.WithTimeout(ctx, 5*time.Second); defer cancel()`. The `defer cancel()` is mandatory — it releases resources even on success.
- Use `context.WithoutCancel(parent)` (Go 1.21+) when you need a context that inherits values but not cancellation (e.g., audit log writes that should outlive the request).
- Check `ctx.Err()` in long-running loops to honor cancellation.

## Naming and structure

- Package names are short, lowercase, single word (`api`, `push`, `db`). Avoid `util`, `common`, `helpers`.
- Exported names are documented with a comment that begins with the name itself: `// New returns a fresh Server.`
- Receiver names are descriptive and consistent across methods of the same type. `server *Server`, not `s *Server`. (Project convention overrides the older Go style guide that recommended 1–3 character receivers — see SKILL.md "avoid one- and two-letter names" rule.)
- Interfaces are defined in the package that uses them, not the package that implements them. (Accept interfaces, return concrete types.)
- One-method interfaces end in `-er` when natural (`Reader`, `Encoder`).
- Group related code in the same file; don't artificially scatter across many small files. A 600-line `handlers.go` is fine.

## Modern features (Go 1.22+)

- `range` over an integer: `for i := range 10 { ... }`.
- `slices` and `maps` packages for common operations.
- `cmp` package for `cmp.Or` (first non-zero value), `cmp.Compare`.
- `slog` for structured logging — see `observability.md`.
- `errors.Join` for aggregating.
- Loop variable scoping is per-iteration in 1.22+; older `i := i` workarounds are no longer needed.

## Constants and enums

- Group related constants in `const ( ... )` blocks with `iota` for enums.
- Give the enum a type: `type Severity int`. This catches mixing with raw ints.
- Provide a `String()` method when values are logged or serialized.
- For string enums (e.g., status values stored in DB), use `type Status string` with explicit values, not iota.

## Generics

- Use generics when the alternative is `interface{}` plus runtime type assertions, OR when copy-pasting the same function for several concrete types.
- Don't use generics to make code "more flexible" speculatively. Concrete types until generics earn their keep.

## Avoid

- `init()` functions for anything beyond registration (e.g., `database/sql.Register`). Initialization that can fail belongs in a constructor.
- Global mutable state. Pass dependencies through constructors.
- `interface{}` / `any` parameters where a typed alternative exists.
- Empty structs with methods used as namespaces. Use a package or a free function.
- Re-exporting symbols from sub-packages "for convenience" — creates import cycles.
