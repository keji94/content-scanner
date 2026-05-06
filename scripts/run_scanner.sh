#!/usr/bin/env bash
# run_scanner.sh — Content Scanner 一键封装脚本
# Phase 1 全自动执行，Phase 2 输出待检段落供 Agent 处理
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="/tmp/content-scanner-$$"

usage() {
  cat <<EOF
Usage: $0 --input <file> --workspace <ws> --output <out.json> [options]

Required:
  --input FILE       Content file to scan
  --workspace DIR    Workspace directory (contains context/ and rules/)
  --output FILE      Output report JSON path

Optional:
  --project NAME     Project name for report (default: content-factory)
  --content-id ID    Content ID for report (default: "")
  --skip-phase2      Skip Phase 2 LLM checks, only run deterministic
  --help             Show this help
EOF
  exit 1
}

INPUT=""
WORKSPACE=""
OUTPUT=""
PROJECT="content-factory"
CONTENT_ID=""
SKIP_PHASE2=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)     INPUT="$2"; shift 2 ;;
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --output)    OUTPUT="$2"; shift 2 ;;
    --project)   PROJECT="$2"; shift 2 ;;
    --content-id) CONTENT_ID="$2"; shift 2 ;;
    --skip-phase2) SKIP_PHASE2=true; shift ;;
    --help|-h)   usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

[[ -z "$INPUT" ]]     && { echo "Error: --input required" >&2; usage; }
[[ -z "$WORKSPACE" ]] && { echo "Error: --workspace required" >&2; usage; }
[[ -z "$OUTPUT" ]]    && { echo "Error: --output required" >&2; usage; }
[[ -f "$INPUT" ]]     || { echo "Error: input file not found: $INPUT" >&2; exit 1; }
[[ -d "$WORKSPACE" ]] || { echo "Error: workspace dir not found: $WORKSPACE" >&2; exit 1; }

CONFIG="$WORKSPACE/context/domain-config.yaml"
CONTEXT_SOURCES="$WORKSPACE/context/context-sources.yaml"
RULES_DET="$WORKSPACE/rules/deterministic"
RULES_LLM="$WORKSPACE/rules/llm"

mkdir -p "$TMP"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "==> Step 1: Split text" >&2
python3 "$SCRIPT_DIR/split_text.py" \
  --input "$INPUT" \
  --config "$CONFIG" \
  > "$TMP/split.json"

echo "==> Step 2: Phase 1 deterministic scan" >&2
python3 "$SCRIPT_DIR/run_deterministic.py" \
  --input "$INPUT" \
  --rules-dir "$RULES_DET" \
  --config "$CONFIG" \
  --context-dir "$WORKSPACE/context" \
  > "$TMP/phase1_violations.json"

if [[ "$SKIP_PHASE2" == "true" ]]; then
  echo "==> Phase 2: skipped (--skip-phase2)" >&2
  cp "$TMP/phase1_violations.json" "$TMP/all_violations.json"
else
  echo "==> Step 3: Phase 2 LLM preparation" >&2

  # 3a: Init context
  python3 "$SCRIPT_DIR/update_context.py" \
    --init \
    --context-json "$TMP/context.json" \
    --extractions /dev/null \
    --config "$CONFIG" \
    --context-sources "$CONTEXT_SOURCES" \
    --unit-index 0

  # 3b: Prepare phase 2 units
  mkdir -p "$TMP/phase2_units"

  # Count l2 units from split.json
  UNIT_COUNT=$(python3 -c "
import json, sys
data = json.load(open('$TMP/split.json'))
units = data.get('l2_units', [])
print(len(units))
")

  echo "    Preparing $UNIT_COUNT units for Phase 2..." >&2

  for i in $(seq 0 $((UNIT_COUNT - 1))); do
    python3 "$SCRIPT_DIR/prepare_phase2_unit.py" \
      --split-json "$TMP/split.json" \
      --context-json "$TMP/context.json" \
      --phase1-violations "$TMP/phase1_violations.json" \
      --config "$CONFIG" \
      --rules-dir "$RULES_LLM" \
      --unit-index "$i" \
      > "$TMP/phase2_units/unit_${i}.json" 2>/dev/null || true
  done

  # Phase 2 violations are empty until Agent processes the units
  echo "[]" > "$TMP/phase2_violations.json"

  # Merge phase1 + empty phase2
  python3 -c "
import json
p1 = json.load(open('$TMP/phase1_violations.json'))
p2 = json.load(open('$TMP/phase2_violations.json'))
if isinstance(p1, dict):
    violations = p1.get('violations', [])
elif isinstance(p1, list):
    violations = p1
else:
    violations = []
violations.extend(p2)
json.dump(violations, open('$TMP/all_violations.json', 'w'), ensure_ascii=False, indent=2)
"
fi

echo "==> Step 4: Calculate score" >&2
python3 "$SCRIPT_DIR/calculate_score.py" \
  --violations "$TMP/all_violations.json" \
  --config "$CONFIG" \
  > "$TMP/score.json"

echo "==> Step 5: Generate report" >&2
REPORT_ARGS=(--violations "$TMP/all_violations.json" --score "$TMP/score.json" --split "$TMP/split.json" --config "$CONFIG")
[[ -n "$PROJECT" ]] && REPORT_ARGS+=(--project "$PROJECT")
[[ -n "$CONTENT_ID" ]] && REPORT_ARGS+=(--content-id "$CONTENT_ID")

python3 "$SCRIPT_DIR/generate_report.py" "${REPORT_ARGS[@]}" \
  > "$OUTPUT"

echo "==> Done. Report: $OUTPUT" >&2
cat "$OUTPUT"
