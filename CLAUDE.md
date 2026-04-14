# Content Scanner - Claude Code Integration

## Overview

This project is a content scanning skill. When invoked, scan text content against configurable rules, produce a scored report, and optionally enter a fix loop.

**Architecture**: Three-phase scanning — Phase 1 is deterministic Python scripts (zero LLM cost), Phase 2 is LLM semantic analysis per paragraph, Phase 3 is multi-reader-perspective review.

## Prerequisites

- Python 3.10+
- Install: `pip install pyyaml jieba`
- A workspace directory containing: `rules/deterministic/`, `rules/llm/`, `context/domain-config.yaml`, `context/context-sources.yaml`

## Invocation

Users invoke via `/content-scanner` or by asking Claude to scan content.

Auto-activates when user mentions: "scan", "check content", "content quality", "content audit", "run scanner", "内容扫描", "检查内容"

## Execution Workflow

Follow the 5-step workflow below. Use **Bash tool** for all Python script calls. Use **your own LLM reasoning** for Phase 2 semantic checks.

### Parameters

Parse from user input or `$ARGUMENTS`:
- `content_path` (required): text file to scan
- `workspace_path` (required): workspace with rules/ and context/
- `genre` (optional, default: from domain-config or "general")
- `check_mode` (optional, default: "full")

```
SCRIPTS_DIR = <project_root>/scripts
TMP = /tmp/content-scanner
```

Create temp dir: `mkdir -p $TMP`

### Step 1: Split Text

```bash
python3 $SCRIPTS_DIR/split_text.py \
  --input <content_path> \
  --config <workspace_path>/context/domain-config.yaml
```

Save stdout to `$TMP/split.json`

### Step 2: Phase 1 Deterministic Check

```bash
python3 $SCRIPTS_DIR/run_deterministic.py \
  --input <content_path> \
  --rules-dir <workspace_path>/rules/deterministic \
  --config <workspace_path>/context/domain-config.yaml \
  --context-dir <workspace_path>/context \
  --genre <genre>
```

Save stdout to `$TMP/phase1_violations.json`

### Step 3: Phase 2 LLM Deep Check

#### 3a. Initialize Context

```bash
python3 $SCRIPTS_DIR/update_context.py \
  --init \
  --context-json $TMP/context.json \
  --extractions /dev/null \
  --config <workspace_path>/context/domain-config.yaml \
  --context-sources <workspace_path>/context/context-sources.yaml \
  --unit-index 0
```

#### 3b. Per-Paragraph Loop

Read `$TMP/split.json` to get total paragraph count N.

FOR each unit_index (0..N-1):

**i. Assemble prompt:**
```bash
python3 $SCRIPTS_DIR/prepare_phase2_unit.py \
  --split-json $TMP/split.json \
  --context-json $TMP/context.json \
  --phase1-violations $TMP/phase1_violations.json \
  --config <workspace_path>/context/domain-config.yaml \
  --unit-index <N> \
  --rules-dir <workspace_path>/rules/llm \
  --learned-dir <workspace_path>/rules/learned
```

**ii. LLM semantic check (batched):**

The output contains `rule_batches` — an array of batches ordered by priority (critical → warning → suggestion). Each batch has `{batch_label, priority, rules}`.

For each batch in `rule_batches`:
1. Use **your own LLM reasoning** to check the paragraph content against the rules in this batch
2. Return a JSON array of violations (or empty array if none)
3. **Early exit optimization**: If `rule_filtering.skip_lower_priority_on_critical` is true and the current batch found critical violations, you MAY skip remaining lower-priority batches for this paragraph

If `rule_batches` is absent (backward compat), fall back to loading rules manually:
- Read LLM rules from `<workspace_path>/rules/llm/*.yaml`
- Read active learned rules from `<workspace_path>/rules/learned/*.yaml`
- Check all rules in a single pass

**iii. Extract context and update:**
- Extract key_facts, character_states, information_revealed from the paragraph
- Write extractions to `$TMP/extractions.json`
- Update context:
```bash
python3 $SCRIPTS_DIR/update_context.py \
  --context-json $TMP/context.json \
  --extractions $TMP/extractions.json \
  --config <workspace_path>/context/domain-config.yaml \
  --context-sources <workspace_path>/context/context-sources.yaml \
  --unit-index <N> \
  --unit-text "<paragraph text>"
```

- Collect LLM violations into `llm_violations[]`

### Step 3.5: Phase 3 Multi-Perspective Review

#### 3.5a. Prepare perspectives

```bash
python3 $SCRIPTS_DIR/run_perspectives.py \
  --config <workspace_path>/context/domain-config.yaml \
  --genre <genre> \
  --default-perspectives <project_root>/perspectives/default-perspectives.yaml
```

Save stdout to `$TMP/perspectives.json`

#### 3.5b. Execute perspective review

Read `$TMP/perspectives.json` to get the 3 reader perspectives and `weight`.

Using **your own LLM reasoning**, review the **full article** (not paragraph-by-paragraph) from each perspective:

For each perspective:
1. Adopt the persona described in `avatar`
2. Focus evaluation on the `focus` areas
3. Ignore concerns listed in `anti_focus`
4. Output a JSON object:
```json
{
  "perspective_id": "P-WR-01",
  "perspective_name": "网文老读者",
  "score": 7,
  "verdict": "one-line summary from this reader's standpoint",
  "likes": ["what this reader would appreciate"],
  "dislikes": ["what this reader would complain about"],
  "suggestions": ["specific improvement suggestions from this perspective"]
}
```

Scale: 1-10, where 7+ means this reader would recommend the article.

Save all 3 perspective results to `$TMP/perspective_results.json`

### Step 4: Merge & Score

Merge Phase 1 + Phase 2 violations into `$TMP/all_violations.json`, then:

```bash
python3 $SCRIPTS_DIR/calculate_score.py \
  --violations $TMP/all_violations.json \
  --config <workspace_path>/context/domain-config.yaml \
  --perspectives $TMP/perspective_results.json
```

Save stdout to `$TMP/score.json`

### Step 5: Generate Report

```bash
python3 $SCRIPTS_DIR/generate_report.py \
  --violations $TMP/all_violations.json \
  --score $TMP/score.json \
  --split $TMP/split.json \
  --config <workspace_path>/context/domain-config.yaml \
  --perspectives $TMP/perspective_results.json \
  --project <project_name> \
  --content-id <content_id>
```

Present the report to the user with grade, score, and top issues.

## Fix Loop

If score < convergence.score:
1. Present findings to user
2. On user approval, apply fixes (via fix_agent or inline editing)
3. Identify which paragraphs were modified (diff the content)
4. **Round 1**: Full re-scan (Steps 1-5, including Phase 3)
5. **Round 2+**: Selective re-scan:
   - Phase 1: Always full re-scan (chapter-level statistics)
   - Phase 2: Only re-check `affected_paragraphs = modified ± 1`
   - Use `--affected-paragraphs` flag on prepare_phase2_unit.py
   - Use `--baseline-violations` + `--affected-paragraphs` on calculate_score.py for diff scoring
6. Track rounds against `fix_loop.max_rounds` (default 3)
7. Stagnation detection: if score delta <= stagnation_delta, warn user and ask whether to continue

Convergence: `critical == 0 AND warning <= convergence.warning AND score >= convergence.score`

## Upstream Integration

For upstream Agent integration guide, see `UPSTREAM.md` — calling interfaces, output JSON schemas, fix loop orchestration protocol, and error handling.

## AIGC Harness

For AI-generated content detection and remediation, see `aigc-harness/SKILL.md`.
Trigger when user says: "AI味太重", "AIGC分数太高", "降AI味", "too AI-generated"

## gstack

Use the `/browse` skill from gstack for all web browsing. **Never use `mcp__claude-in-chrome__*` tools.**

Available gstack skills: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/design-shotgun`, `/design-html`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/connect-chrome`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/retro`, `/investigate`, `/document-release`, `/codex`, `/cso`, `/autoplan`, `/plan-devex-review`, `/devex-review`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`, `/learn`
