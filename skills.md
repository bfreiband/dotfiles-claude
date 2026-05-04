# Skills

`go-backend-pro` lives in `skills/` in this repo — `install.sh` symlinks it into `~/.claude/skills/`.

The skills below are managed by an external skill-installer that drops content into `~/.agents/skills/` and symlinks `~/.claude/skills/<name> -> ../../.agents/skills/<name>`. They're not tracked here. On a new machine, install them via whatever skill-installer you use (e.g. the `find-skills` skill once bootstrapped), pointing it at the upstream sources.

| Skill | Upstream |
|---|---|
| `find-skills` | https://github.com/vercel-labs/skills (path: `skills/find-skills`) |
| `swift-concurrency-pro` | https://github.com/twostraws/swift-concurrency-agent-skill |
| `swift-testing-pro` | https://github.com/twostraws/swift-testing-agent-skill |
| `swiftui-pro` | https://github.com/twostraws/swiftui-agent-skill |

To bootstrap on a fresh machine without the installer, the cheap fallback is to clone each upstream repo into `~/.agents/skills/<name>` (or wherever) and create the symlink manually:

```sh
mkdir -p ~/.agents/skills
# example for swift-concurrency-pro
git clone https://github.com/twostraws/swift-concurrency-agent-skill ~/.agents/skills/swift-concurrency-pro
ln -s ../../.agents/skills/swift-concurrency-pro ~/.claude/skills/swift-concurrency-pro
```
