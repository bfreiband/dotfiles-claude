#!/usr/bin/env bash
# Symlink tracked files from this repo into ~/.claude/.
# Backs up any existing non-symlink target to <path>.pre-dotfiles before linking.

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="${HOME}/.claude"

mkdir -p "$DEST/hooks" "$DEST/skills"

link() {
  local src="$1" dst="$2"
  if [[ -L "$dst" ]]; then
    rm "$dst"
  elif [[ -e "$dst" ]]; then
    mv "$dst" "${dst}.pre-dotfiles"
    echo "  backed up existing $dst -> ${dst}.pre-dotfiles"
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

# Verify env file exists for push-notify
if [[ ! -f "$DEST/hooks/push-notify.env" ]]; then
  echo
  echo "WARNING: $DEST/hooks/push-notify.env is missing."
  echo "Copy hooks/push-notify.env.example to that path and fill in your Pushover credentials."
fi

echo
echo "Done. Restart Claude Code to pick up settings.json changes."
