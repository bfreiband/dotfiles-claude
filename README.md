# dotfiles-claude

Personal Claude Code configuration synced across machines.

## What's tracked

- `settings.json` — statusline, hooks, enabled plugins, marketplaces (portable config only; machine-specific overrides go in `settings.local.json`)
- `hooks/push-notify.sh` — Pushover notification hook (reads credentials from `~/.claude/hooks/push-notify.env`, which is **not** in this repo)
- `hooks/push-notify.env.example` — template for the credentials file
- `skills/go-backend-pro/` — custom user-level skill (the only one whose content lives in this repo)
- `xdg/.config/<tool>/` — configs for tools that read from `$XDG_CONFIG_HOME` (currently just `ccstatusline`); supports `.local.json` overlays
- `mcp-servers.md` — commands to re-add user-scoped MCP servers on a new machine

## What's not tracked

Runtime state (`projects/`, `sessions/`, `tasks/`, `todos/`, `history.jsonl`, `file-history/`, etc.), per-project memory, plugin caches, `~/.claude.json` (mixes config with state and auth tokens), and `*.local.json` overlay files.

## How it works

The installer **copies** files (not symlinks) to their system destinations. JSON targets (`settings.json`, `ccstatusline/settings.json`) are first merged with an optional `.local.json` overlay before writing. This means:

- The repo contains only portable config that works on any machine
- Machine-specific overrides (Bedrock/AWS env vars, corp plugins, model ID) live in gitignored `*.local.json` files next to their base
- Re-run `./install.py` after editing either the repo file or the `.local.json` overlay

### Overlay merge rules

- **`settings.json`** (`claude-settings` profile): dicts recurse, scalars from `.local` win, `hooks.*` arrays are unioned (deduplicated by normalized command signature)
- **Other JSON** (`generic` profile): dicts recurse, scalars/arrays from `.local` replace wholesale (no union)

### Example: `settings.local.json`

```json
{
  "awsAuthRefresh": "exec duo-sso -profile claudecode -valid-session-threshold 7200",
  "model": "us.anthropic.claude-opus-4-7",
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "true",
    "AWS_PROFILE": "claudecode",
    "AWS_SDK_LOAD_CONFIG": "1"
  }
}
```

## Install on a new machine

Requires [`uv`](https://docs.astral.sh/uv/) (the installer is a single-file PEP 723 script — `uv` pulls Python and runs it without a venv).

```sh
git clone git@github.com:<you>/dotfiles-claude.git ~/src/dotfiles-claude
cd ~/src/dotfiles-claude

# 1. Dry-run the plan first — shows exactly what will change
./install.py --dry-run

# 2. Apply it (prompts per conflict)
./install.py

# 3. If push-notify.env wasn't salvaged from an existing setup, drop creds in now
cp hooks/push-notify.env.example ~/.claude/hooks/push-notify.env
chmod 600 ~/.claude/hooks/push-notify.env
$EDITOR ~/.claude/hooks/push-notify.env

# 4. (Optional) Create a settings.local.json for machine-specific config
$EDITOR settings.local.json
./install.py --only settings

# 5. Re-add MCP servers (see mcp-servers.md)
```

Upstream-managed skills (the `skills.md` table) are installed automatically by `install.py` via `npx skills add ... -g --agent claude-code -y`. Node.js/npx must be on PATH; otherwise the installer will error before touching the filesystem.

### Reconciling live edits

If you edit `~/.claude/settings.json` directly (or another managed file), those changes won't automatically sync back. Use `reconcile.py` to route them:

```sh
# See what drifted
./reconcile.py --dry-run

# Interactively route each change to repo, .local overlay, or discard
./reconcile.py
```

For each difference, you choose:
- **repo** — write into the committed file (for portable changes)
- **local** — write into `.local.json` (for machine-specific changes)
- **discard** — next `./install.py` run will overwrite with expected content
- **skip** — leave as-is for now

### How `install.py` handles an already-configured machine

- **First run (migration):** if no `settings.local.json` exists, the installer detects machine-specific keys (AWS/Bedrock, corp plugins) in the repo `settings.json` and offers to extract them into `settings.local.json`.
- **Identical targets** are no-ops — safe to re-run anytime.
- **Drifted targets** (live file differs from expected) show a diff and let you take-expected / keep / abort.
- **Hardcoded Pushover credentials** in an existing `push-notify.sh` are detected and offered for salvage into `push-notify.env`.
- **Backups** of overwritten targets go to `~/.dotfiles-claude-backups/`.
- **Skill directories** are copied file-by-file; orphaned files (in destination but not repo) are prompted for cleanup.

Flags: `--dry-run`, `--yes` (non-interactive; safe defaults), `--only {settings,hooks,skills,skills-upstream,xdg}` (repeatable), `--verbose`.

## Assumptions

- Plugins listed under `enabledPlugins` are pulled from their marketplaces by Claude Code on first run; nothing to do manually.
