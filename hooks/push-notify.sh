#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${HOME}/.claude/hooks/push-notify.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "push-notify: missing $ENV_FILE — copy push-notify.env.example and fill in your Pushover credentials" >&2
  exit 0
fi
# shellcheck source=/dev/null
source "$ENV_FILE"

input=$(cat)

{ read -r title; read -r message; } < <(python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
if d.get('hook_event_name') == 'Stop':
    title = 'Claude: done'
    msg = d.get('last_assistant_message', '') or 'Finished'
    message = next((l.strip() for l in msg.splitlines() if l.strip()), 'Finished')
else:
    title = d.get('title', 'Claude')
    message = d.get('message', 'Needs your attention')
print(title)
print(message[:200])
" <<< "$input")

curl -s \
  --form-string "token=${PUSHOVER_TOKEN}" \
  --form-string "user=${PUSHOVER_USER}" \
  --form-string "title=$title" \
  --form-string "message=$message" \
  https://api.pushover.net/1/messages.json \
  > /dev/null
