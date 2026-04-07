# Content Scanner Tools

## Platform Tools Used

- **shell**: Execute Python CLI scripts
- **file**: Read/write temporary JSON files, read workspace YAML configs

No browser tool required.

## Python Scripts

### split_text

L1/L2 text splitting.

```bash
python3 scripts/split_text.py --input <file> --config <domain-config.yaml>
```

**Output**:
```json
{ "l1_units": [...], "l2_units": [...], "l2_to_l1": {...}, "metadata": {...} }
```

### run_deterministic

Phase 1 deterministic rule engine (11 rule types, zero LLM cost).

```bash
python3 scripts/run_deterministic.py \
  --input <file> \
  --rules-dir <rules/deterministic/> \
  --config <domain-config.yaml> \
  --context-dir <context/> \
  --genre <genre>
```

**Output**:
```json
{
  "violations": [{ "rule_id", "rule_name", "location", "original_text", "severity", "weight", "issue", "source": "deterministic" }],
  "summary": { ... }
}
```

### prepare_phase2_unit

Assemble Phase 2 prompt structure for one paragraph.

```bash
python3 scripts/prepare_phase2_unit.py \
  --split-json <split.json> \
  --context-json <context.json> \
  --phase1-violations <phase1_violations.json> \
  --config <domain-config.yaml> \
  --unit-index <N>
```

**Output**:
```json
{
  "system_prompt": "...",
  "context": "...",
  "domain_context": "...",
  "phase1_hints": "...",
  "content": "...",
  "output_format": "..."
}
```

### update_context

Initialize or update cumulative context.

```bash
# Init mode
python3 scripts/update_context.py \
  --init \
  --context-json <context.json> \
  --extractions /dev/null \
  --config <domain-config.yaml> \
  --context-sources <context-sources.yaml> \
  --unit-index 0

# Update mode
python3 scripts/update_context.py \
  --context-json <context.json> \
  --extractions <extractions.json> \
  --config <domain-config.yaml> \
  --context-sources <context-sources.yaml> \
  --unit-index <N> \
  --unit-text "<paragraph text>"
```

### calculate_score

Score computation with correlation grouping and deduplication.

```bash
python3 scripts/calculate_score.py \
  --violations <all_violations.json> \
  --config <domain-config.yaml>
```

**Output**:
```json
{
  "score": 85, "grade": "B", "deduction": 15,
  "critical_count": 2, "warning_count": 6,
  "suggestion_count": 0, "total_violations": 8
}
```

### generate_report

Final report assembly.

```bash
python3 scripts/generate_report.py \
  --violations <all_violations.json> \
  --score <score.json> \
  --split <split.json> \
  --config <domain-config.yaml> \
  --project <name> \
  --content-id <id>
```

**Output**: Complete JSON report (see SKILL.md report format).

## LLM Tool

The platform's native LLM is used for Phase 2 semantic checks. No custom LLM tool is needed — the agent uses its configured model to reason about the prompt structure produced by `prepare_phase2_unit.py`.
