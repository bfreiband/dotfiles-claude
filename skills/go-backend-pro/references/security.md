# Security

Most server-side bugs are security bugs in disguise. Default to paranoid; loosen only with a clear reason.

## Input validation

- Validate at the boundary (HTTP handler, message consumer). Internal code trusts already-validated data.
- Validate types via JSON decode + `DisallowUnknownFields`. Validate semantics (length, ranges, enums) explicitly.
- Use a validation pattern, not ad-hoc `if`s scattered through the handler:
  ```go
  if v.URL == "" || len(v.URL) > 2048 { return errBadRequest("url required, ≤2048 chars") }
  if v.Severity < 1 || v.Severity > 10 { return errBadRequest("severity 1–10") }
  ```
- Never trust client-supplied IDs for authorization. The endpoint authorizes based on the session, not the request body.

## SQL injection

- All SQL is parameterized. `$1`, `$2` placeholders. Period.
- `fmt.Sprintf` building SQL is a defect even when "safe" inputs are involved — the policy must be invariant.
- Identifier interpolation (table/column names from input) is dangerous. If you must, use an allowlist; never let the user pick the column.

## JWT / SIWA

JWTs are easy to misuse. Specifically for Apple Sign in with Apple:

- Verify `alg` matches what you expect (`RS256` for Apple). Reject `alg: none`. Reject unexpected algorithms.
- Verify `iss == "https://appleid.apple.com"`.
- Verify `aud == <your bundle ID>` (or service ID for web).
- Verify `exp` is in the future and `iat` is in the past (allow ~5 min skew).
- Verify the signature using Apple's JWKS, fetched from `https://appleid.apple.com/auth/keys`. Cache for 1h, refresh with `singleflight`.
- Find the right key by `kid` in the token header. Don't try keys at random.
- If using nonces, verify the nonce on the server matches what the client claims.

Use a vetted library: `github.com/go-jose/go-jose` or `github.com/lestrrat-go/jwx`. Don't hand-roll JWT parsing.

## Session tokens

- Generate with `crypto/rand`, ≥ 32 bytes, base64url-encoded. Don't use UUIDs (insufficient entropy).
- Store the SHA-256 hash in the DB, not the raw token. Compare with `subtle.ConstantTimeCompare` after hashing the presented token.
- Session lifetime: 90 days rolling is a reasonable default. Refresh in-place by issuing a new token in a response header when a request arrives near expiry.
- Mark tokens as revoked on signout; don't delete (history matters).

## Secret handling

- Secrets come from env vars (`fly secrets`), never from code or config files.
- Never log a secret. If you must debug, log a SHA-256 prefix.
- `.env.local` in `.gitignore`. Use `.env.example` (committed) as a template.
- APNs `.p8` key file or contents — load from secret env var. Don't bake into the image.
- Rotate secrets when team changes; have a documented rotation process.

## Constant-time comparison

- Use `subtle.ConstantTimeCompare(a, b) == 1` for any secret comparison (tokens, HMACs, signatures).
- Plain `==` on strings short-circuits and leaks length / prefix info via timing.

## CORS

- Default deny. Don't enable CORS unless you have a real cross-origin client.
- If needed, allowlist exact origins (`https://horrors.test`, `https://persistenthorrors.app`). Never `Access-Control-Allow-Origin: *` for authenticated endpoints.
- Set `Access-Control-Allow-Credentials: true` only when needed and only with explicit origins.

## Rate limiting

- Public endpoints (especially auth-adjacent) need rate limits.
- Token bucket per IP for unauthenticated endpoints (`golang.org/x/time/rate`).
- Per-user-id limits for authenticated write endpoints (votes, submissions).
- Rate-limit responses use `429 Too Many Requests` with `Retry-After` header.

## TLS

- Production has TLS terminated at Fly's edge. The Go server speaks plain HTTP inside the network.
- For SIWA you only need TLS on the user-facing edge; Fly handles this.
- Local dev can be plain HTTP except for the `/admin` SIWA-web flow, which uses Caddy + mkcert.

## Common pitfalls

- **Open redirects**: a `redirect_to` query param taken at face value. Allowlist destinations or restrict to relative paths.
- **SSRF**: a feature that fetches a user-supplied URL. Restrict scheme to `https`, block private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, link-local).
- **Mass assignment**: decoding a request body into a DB struct directly. Define request structs separate from DB structs; map field-by-field.
- **IDOR (Insecure Direct Object Reference)**: `/v1/votes/:id` where any user can view any vote. Authorize by `votes.user_id == ctx.UserID`.
- **CSRF**: only relevant for cookie-authed routes. The public API uses Bearer tokens (immune). Admin web uses cookies and needs CSRF tokens on POST forms.
- **Subdomain takeover**: dangling DNS records pointing at a deprovisioned host. Audit DNS regularly.

## Logging hygiene

- Never log: passwords, session tokens, APNs tokens, SIWA identity tokens, .p8 contents, any secret.
- Logs are exported. Anything logged is potentially leaked. Treat them like external surface.

## Headers

- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` (set at edge).
- `X-Content-Type-Options: nosniff`.
- `Content-Security-Policy` for any HTML response (admin web). Default-src 'self' + explicit allowances.
- `Referrer-Policy: strict-origin-when-cross-origin`.

## Don't

- Don't roll your own crypto. Use stdlib `crypto/...` or vetted libraries.
- Don't store secrets in client-readable places (CDN-cached responses, error messages, debug pages).
- Don't disable TLS verification "temporarily." It tends to ship.
- Don't use weak hashes (`md5`, `sha1`) for anything security-relevant.
