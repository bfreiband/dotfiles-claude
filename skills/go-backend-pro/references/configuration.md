# Configuration

A misconfigured server is the most common production incident. Config should be loud, not silent.

## Source of truth: env vars

- All configuration comes from environment variables. Not flags, not files, not embedded constants for env-specific values.
- This matches 12-factor and matches how Fly (and any modern container platform) injects secrets.
- One exception: build-time constants (version string, commit SHA) baked via `-ldflags`.

## Loading

- Define a single `Config` struct populated at startup. Pass it (or its slices) into constructors.
- Validate at startup. Fail fast — log the missing var, exit non-zero. Don't allow the process to come up in a broken state and discover it at request time.

```go
type Config struct {
    Port                int
    DatabaseURL         string
    AppleBundleID       string
    APNsKeyP8           []byte
    APNsKeyID           string
    APNsTeamID          string
    SessionSigningKey   []byte
    AdminAllowlistSubs  []string
    LogLevel            slog.Level
}

func Load() (*Config, error) {
    var c Config
    var missing []string

    c.Port = envInt("PORT", 8080) // default OK for non-secret operational config
    c.DatabaseURL = mustEnv("DATABASE_URL", &missing)
    c.AppleBundleID = mustEnv("APPLE_BUNDLE_ID", &missing)
    p8 := mustEnv("APNS_KEY_P8", &missing)
    c.APNsKeyP8 = []byte(p8)
    // ...

    if len(missing) > 0 {
        return nil, fmt.Errorf("missing required env vars: %s", strings.Join(missing, ", "))
    }
    return &c, nil
}

func mustEnv(key string, missing *[]string) string {
    v := os.Getenv(key)
    if v == "" { *missing = append(*missing, key) }
    return v
}
```

## Defaults

- Operational config (port, log level, pool sizes) can have safe defaults.
- Secrets (DB URL, signing keys, API keys) NEVER have defaults. Missing secrets fail startup.
- Environment-shape config (allowlists, feature flags) — depends. Often safer to require explicit setting in prod.

## .env files

- `.env.local` for local development. In `.gitignore`.
- `.env.example` committed, documents required vars with placeholder values.
- Use `godotenv` or similar ONLY for dev. Don't load `.env` files in production — secrets come from `fly secrets`.

```go
if env := os.Getenv("APP_ENV"); env == "" || env == "dev" {
    _ = godotenv.Load(".env.local")
}
```

## Multiple environments

- Don't have multiple config files (`config.dev.yaml`, `config.prod.yaml`). The deployment platform sets the env vars; the binary reads them.
- For genuine env-shape differences (e.g., APNs sandbox vs production endpoint), use a single `APNS_HOST` env var.

## Feature flags

- For toggling features per-environment or per-rollout, use boolean env vars (`SIWA_ENABLED=true`).
- For fine-grained per-user flags, use a real flag service (LaunchDarkly, Statsig, OpenFeature) — but only if you actually need it. Most v1 features don't.

## Don't

- Don't read env vars in random places. Centralize in `Load()`. Anywhere else makes config audit impossible.
- Don't validate env vars lazily ("if missing, treat as empty string"). Fail fast.
- Don't commit `.env` files. Git history makes secret rotation a nightmare.
- Don't put env-specific URLs in code. `https://api.push.apple.com` is fine to default, but `https://api.development.push.apple.com` for sandbox should be configurable.
