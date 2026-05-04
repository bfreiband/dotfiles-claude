#!/usr/bin/env bash
# Symlink tracked files from this repo into their target locations
# (~/.claude/ for Claude Code config, ~/.config/<tool>/ for XDG-config tools).
# Backs up any existing non-symlink target into BACKUP_ROOT before linking.
#
# Backups go OUTSIDE any tool-scanned directory: previously they landed in
# place as <path>.pre-dotfiles, but Claude Code scans ~/.claude/skills/ for
# any subdir with a SKILL.md, so a backup of go-backend-pro/ became a phantom
# duplicate skill. Out-of-tree backups avoid that class of problem entirely.

set -euo pipefail
shopt -s nullglob

REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="${HOME}/.claude"
XDG_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
BACKUP_ROOT="${HOME}/.dotfiles-claude-backups"

mkdir -p "$DEST/hooks" "$DEST/skills" "$XDG_CONFIG"

link() {
  local src="$1" dst="$2"
  if [[ -L "$dst" ]]; then
    rm "$dst"
  elif [[ -e "$dst" ]]; then
    # Mirror the destination path under BACKUP_ROOT, relative to $HOME when
    # possible so the backup tree is self-describing.
    local rel="$dst"
    [[ "$dst" == "$HOME"/* ]] && rel="${dst#$HOME/}"
    local backup="$BACKUP_ROOT/$rel"
    if [[ -e "$backup" || -L "$backup" ]]; then
      backup="${backup}.$(date +%Y%m%d-%H%M%S)"
    fi
    mkdir -p "$(dirname "$backup")"
    mv "$dst" "$backup"
    echo "  backed up existing $dst -> $backup"
  fi
  ln -s "$src" "$dst"
  echo "  linked $dst -> $src"
}

# Top-level files
link "$REPO/settings.json" "$DEST/settings.json"

# Hooks
link "$REPO/hooks/push-notify.sh" "$DEST/hooks/push-notify.sh"

# Skills (link each skill directory individually so unrelated skills in
# ~/.claude/skills are left alone)
for skill_dir in "$REPO/skills"/*/; do
  name="$(basename "$skill_dir")"
  link "${skill_dir%/}" "$DEST/skills/$name"
done

# XDG config dirs (e.g. ccstatusline) — link each tool dir individually so
# unrelated tools' configs in ~/.config are left alone.
if [[ -d "$REPO/xdg/.config" ]]; then
  for tool_dir in "$REPO/xdg/.config"/*/; do
    name="$(basename "$tool_dir")"
    link "${tool_dir%/}" "$XDG_CONFIG/$name"
  done
fi

# Verify env file exists for push-notify
if [[ ! -f "$DEST/hooks/push-notify.env" ]]; then
  echo
  echo "WARNING: $DEST/hooks/push-notify.env is missing."
  echo "Copy hooks/push-notify.env.example to that path and fill in your Pushover credentials."
fi

echo
echo "Done. Restart Claude Code to pick up settings.json changes."
