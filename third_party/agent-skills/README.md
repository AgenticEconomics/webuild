# WeBuild Agent Skills (vendored)

Skills imported for Phase VI from
[AgenticEconomics/skills](https://github.com/AgenticEconomics/skills).

## Layout

```
default-skills/<skill-name>/SKILL.md   # WeBuild auto-install plugin root
.webuild-plugin/marketplace.json
SOURCE.md / NOTICE.md
```

On startup, WeBuild syncs this tree to `~/.webuild/marketplaces/agent-skills`
(or uses `/opt/webuild/agent-skills` in the sandbox image) and auto-installs
the `default-skills` plugin.

## Using

Skills appear in `/skills` and are eligible for automatic skill selection
by description. Invoke by name (e.g. ask to create a PDF, or mention
frontend design). Document skills may need Python/Node packages at runtime
(`pypdf`, `openpyxl`, `docx`, Playwright, etc.).

## License

See [NOTICE.md](./NOTICE.md) and each skill's `LICENSE.txt`.
