---
name: gstack
preamble-tier: 1
version: 1.1.0
description: |
  Fast headless browser for QA testing and site dogfooding. Navigate pages, interact with
  elements, verify state, diff before/after, take annotated screenshots, test responsive
  layouts, forms, uploads, dialogs, and capture bug evidence. Use when asked to open or
  test a site, verify a deployment, dogfood a user flow, or file a bug with screenshots. (gstack)
allowed-tools:
  - Bash(gstack:*)
  - Bash(browse:*)
  - Bash(design:*)
  - Bash(bun:*)
  - Bash(npx:*)
---

# gstack — Install Required

This is a project-level reference to gstack. Each teammate must install it locally first:

```
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup
```

## Skills

Use `/browse` for all web browsing. **Never use `mcp__claude-in-chrome__*` tools.**

Available skills: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/design-shotgun`, `/design-html`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/connect-chrome`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/retro`, `/investigate`, `/document-release`, `/codex`, `/cso`, `/autoplan`, `/plan-devex-review`, `/devex-review`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`, `/learn`
