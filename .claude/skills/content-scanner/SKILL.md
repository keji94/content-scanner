---
name: content-scanner
description: "Scan text content for quality issues using deterministic rules and LLM semantic checks. Invoke with /content-scanner or when user asks to scan/check content quality."
allowed-tools: Bash Read Write Grep Glob
---

# Content Scanner Skill

Read the project root `CLAUDE.md` and `SKILL.md` for complete instructions.

## Arguments

Parse `$ARGUMENTS` as:
```
<content_path> [workspace=<path>] [genre=<genre>] [mode=<full|quick>]
```

- `content_path`: required, text file to scan
- `workspace`: optional, defaults to searching parent directories of content_path for domain-config.yaml
- `genre`: optional, defaults to value in domain-config or "general"
- `mode`: optional, defaults to "full"

## Execution

Follow the 5-step workflow in `CLAUDE.md`:
1. Split text
2. Phase 1 deterministic check
3. Phase 2 LLM semantic check (per-paragraph loop)
4. Merge violations + calculate score
5. Generate report

Present results with grade, score, and top issues to user.
