# Skills

`go-backend-pro` lives in `skills/` in this repo — `install.sh` symlinks it into `~/.claude/skills/`.

The skills below are managed by `npx skills` (content lives in `~/.agents/skills/<name>`, with `~/.claude/skills/<name>` symlinked to it). `install.py` parses the table below and runs `npx skills add <url> --skill <name> -g --agent claude-code -y` for any row whose destination is missing — so on a new machine, `./install.py` is enough.

| Skill | Upstream |
|---|---|
| `find-skills` | https://github.com/vercel-labs/skills (path: `skills/find-skills`) |
| `swift-concurrency-pro` | https://github.com/twostraws/swift-concurrency-agent-skill |
| `swift-testing-pro` | https://github.com/twostraws/swift-testing-agent-skill |
| `swiftui-pro` | https://github.com/twostraws/swiftui-agent-skill |

If `npx` isn't available, the fallback is to clone each upstream repo into `~/.agents/skills/<name>` and create the symlink manually:

```sh
mkdir -p ~/.agents/skills
# example for swift-concurrency-pro
git clone https://github.com/twostraws/swift-concurrency-agent-skill ~/.agents/skills/swift-concurrency-pro
ln -s ../../.agents/skills/swift-concurrency-pro ~/.claude/skills/swift-concurrency-pro
```
