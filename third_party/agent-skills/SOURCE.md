# Upstream source

- Repository: https://github.com/AgenticEconomics/skills
- Forked from: https://github.com/anthropics/skills
- Imported commit: `57546260929473d4e0d1c1bb75297be2fdfa1949`
- Import date (UTC): 2026-07-28
- Layout adaptation: upstream `skills/<name>/` → WeBuild `default-skills/<name>/`
  so marketplace auto-install (`default-skills`) and plugin discovery work.

## Refresh

```bash
git clone --depth 1 https://github.com/AgenticEconomics/skills.git /tmp/ae-skills-refresh
# then rsync skills/* into default-skills/ and update this SHA
```
