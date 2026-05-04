# dotfiles-claude

Personal Claude Code configuration synced across machines.

## What's tracked

- `settings.json` — statusline, hooks, enabled plugins, marketplaces
- `hooks/push-notify.sh` — Pushover notification hook (reads credentials from `~/.claude/hooks/push-notify.env`, which is **not** in this repo)
- `hooks/push-notify.env.example` — template for the credentials file
- `skills/go-backend-pro/` — custom user-level skill (the only one whose content lives in this repo)
- `mcp-servers.md` — commands to re-add user-scoped MCP servers on a new machine

## What's not tracked

Runtime state (`projects/`, `sessions/`, `tasks/`, `todos/`, `history.jsonl`, `file-history/`, etc.), per-project memory, plugin caches, and `~/.claude.json` (mixes config with state and auth tokens).

## Install on a new machine

```sh
git clone git@github.com:<you>/dotfiles-claude.git ~/src/dotfiles-claude
cd ~/src/dotfiles-claude

# 1. Drop in your Pushover credentials (won't be committed)
cp hooks/push-notify.env.example ~/.claude/hooks/push-notify.env
chmod 600 ~/.claude/hooks/push-notify.env
$EDITOR ~/.claude/hooks/push-notify.env

# 2. Symlink everything tracked into ~/.claude/
./install.sh

# 3. Re-add MCP servers (see mcp-servers.md)

# 4. Re-install upstream-managed skills (see skills.md)
```

`install.sh` backs up any existing non-symlinked file in `~/.claude/` to `<path>.pre-dotfiles` before linking.

## Assumptions

- `settings.json` uses `$HOME` for hook paths, so different usernames across machines are fine.
- Plugins listed under `enabledPlugins` are pulled from their marketplaces by Claude Code on first run; nothing to do manually.
