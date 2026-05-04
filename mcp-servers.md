# MCP servers

User-scoped MCP servers live in `~/.claude.json`, which isn't tracked in this repo (it mixes config with auth tokens and project state). Re-add them on a new machine with the commands below.

## RuntimeViewer

```sh
claude mcp add --scope user --transport http RuntimeViewer http://127.0.0.1:9277/mcp
```

## Others

`xcode-proxy`, `linear-server`, and similar servers come from installed plugins or are added separately. Check `claude mcp list` on the source machine for the full set, then mirror with `claude mcp add` here.
