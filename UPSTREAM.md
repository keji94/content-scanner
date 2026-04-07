# Content Scanner - 上游对接指引

## 概述

本文档面向**上游 Agent 开发者**，说明如何将 content-scanner 集成为子流程。

content-scanner 提供两种对接方式：

| 方式 | 适用场景 | Agent 职责 |
|------|---------|-----------|
| **完整工作流委托** | 上游只需拿到最终报告 | 传入参数，scanner 执行全部 5 步，返回报告 |
| **单脚本直接调用** | 上游需要精细控制流程 | 按需调用 `run_deterministic.py` / `calculate_score.py` 等独立脚本 |

```
上游 Agent
  │
  ├── 完整委托 ──→ content-scanner ──→ 最终报告 JSON
  │
  └── 单脚本调用 ──→ split_text.py
                   → run_deterministic.py
                   → prepare_phase2_unit.py + LLM 判断
                   → calculate_score.py
                   → generate_report.py
```

---

## 1. 调用接口

### 1.1 完整工作流委托

上游传入以下参数，委托 scanner 执行全流程：

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `content_path` | string | 是 | 待扫描文本文件路径 |
| `workspace_path` | string | 是 | 包含 `rules/` 和 `context/` 的 workspace 路径 |
| `genre` | string | 否 | 内容类型，默认取 domain-config 或 `"general"` |
| `check_mode` | string | 否 | `"full"` / `"quick"`，默认 `"full"` |
| `content_id` | string | 否 | 内容标识（章节名/文章标题） |

触发方式（任选其一）：
- SKILL.md trigger: `upstream` 模式
- 聊天命令: `scan <content_path> workspace=<workspace_path> [genre=<g>] [mode=<full|quick>]`

返回：完整报告 JSON（见 [第 3 节 Report Schema](#3-输出契约)）。

### 1.2 单脚本直接调用

上游按需调用独立 Python 脚本。每个脚本的 CLI 参数见下方。

#### 文本分片

```bash
python3 scripts/split_text.py \
  --input <content_path> \
  --config <workspace>/context/domain-config.yaml
```

#### Phase 1 确定性检查

```bash
python3 scripts/run_deterministic.py \
  --input <content_path> \
  --rules-dir <workspace>/rules/deterministic \
  --config <workspace>/context/domain-config.yaml \
  --context-dir <workspace>/context \
  --genre <genre>
```

#### Phase 2 Prompt 组装（单段）

```bash
python3 scripts/prepare_phase2_unit.py \
  --split-json $TMP/split.json \
  --context-json $TMP/context.json \
  --phase1-violations $TMP/phase1_violations.json \
  --config <workspace>/context/domain-config.yaml \
  --unit-index <N> \
  --rules-dir <workspace>/rules/llm \
  --learned-dir <workspace>/rules/learned
```

上游 Agent 拿到 prompt 结构后，自行用 LLM 判断违规（见 Phase 2 协议）。

#### 上下文初始化 / 更新

```bash
# 初始化
python3 scripts/update_context.py \
  --init \
  --context-json $TMP/context.json \
  --extractions /dev/null \
  --config <workspace>/context/domain-config.yaml \
  --context-sources <workspace>/context/context-sources.yaml \
  --unit-index 0

# 逐段更新
python3 scripts/update_context.py \
  --context-json $TMP/context.json \
  --extractions $TMP/extractions.json \
  --config <workspace>/context/domain-config.yaml \
  --context-sources <workspace>/context/context-sources.yaml \
  --unit-index <N> \
  --unit-text "<段落文本>"
```

#### 评分计算

```bash
python3 scripts/calculate_score.py \
  --violations $TMP/all_violations.json \
  --config <workspace>/context/domain-config.yaml
```

#### 报告生成

```bash
python3 scripts/generate_report.py \
  --violations $TMP/all_violations.json \
  --score $TMP/score.json \
  --split $TMP/split.json \
  --config <workspace>/context/domain-config.yaml \
  --project <project_name> \
  --content-id <content_id>
```

---

## 2. 调用粒度

### `full` — 完整扫描

Phase 1 + Phase 2 全部执行。

```
split_text → run_deterministic → [逐段] prepare_phase2_unit + LLM + update_context → calculate_score → generate_report
```

### `quick` — 仅 Phase 1

零 LLM 成本。适合快速预检或上游只想做确定性检查的场景。

```
split_text → run_deterministic → calculate_score → generate_report --check-mode quick
```

> 注：`quick` 模式下 `generate_report.py` 接受 `--check-mode quick` 参数，报告中 `check_mode` 字段相应标记。

### `phase2-only` — 仅 LLM 语义检查

跳过 Phase 1，直接从 Phase 2 开始。适用于上游已有 Phase 1 结果的场景（如 aigc-harness 的 Fix Loop 复检）。

```
split_text → [跳过 run_deterministic] → [逐段] prepare_phase2_unit + LLM + update_context → 合并已有 Phase 1 violations → calculate_score → generate_report
```

具体做法：
1. 仍需运行 `split_text.py` 获取段落结构
2. 跳过 `run_deterministic.py`，使用已有的 Phase 1 violations 文件
3. 正常执行 Phase 2 逐段循环
4. 合并已有 Phase 1 violations + 新的 LLM violations 到 `all_violations.json`
5. 继续评分和报告步骤

---

## 3. 输出契约

### 3.1 Split JSON（`split_text.py` 输出）

来源脚本：`split_text.py`

```json
{
  "l1_units": [
    { "index": 0, "text": "句子文本", "char_count": 12, "paragraph_index": 0, "global_index": 0 }
  ],
  "l2_units": [
    { "index": 0, "text": "段落文本", "char_count": 45 }
  ],
  "l2_to_l1": { "0": [0, 1, 2] },
  "metadata": {
    "total_paragraphs": 25,
    "total_sentences": 85,
    "total_chars": 3200,
    "l1_separator": "。！？",
    "l2_separator": "'\\n'"
  }
}
```

### 3.2 Phase 1 Violations JSON（`run_deterministic.py` 输出）

来源脚本：`run_deterministic.py`

```json
{
  "violations": [
    {
      "rule_id": "D001",
      "rule_name": "规则名称",
      "location": { "paragraph": 3, "sentence": 1 },
      "original_text": "原文片段",
      "severity": "critical | warning | suggestion",
      "weight": 10,
      "issue": "违规描述",
      "source": "deterministic"
    }
  ],
  "summary": { }
}
```

### 3.3 Phase 2 Violations（LLM 产出）

来源：Agent LLM 语义判断（非脚本输出）

```json
[
  {
    "rule_id": "L001",
    "sentence_index": 2,
    "severity": "critical | warning | suggestion",
    "original_text": "原文片段",
    "issue": "问题描述",
    "suggestion": "修改建议",
    "context_conflict": "与前文的冲突说明（可选）"
  }
]
```

上游 Agent 需将 LLM 违规结果写入 JSON 文件，并为每条违规补充 `source: "llm"` 和 `location` 字段以便与 Phase 1 统一处理：

```json
{
  "rule_id": "L001",
  "sentence_index": 2,
  "severity": "warning",
  "original_text": "...",
  "issue": "...",
  "suggestion": "...",
  "source": "llm",
  "location": { "paragraph": 5, "sentence": 2 }
}
```

### 3.4 Phase 2 Prompt 结构（`prepare_phase2_unit.py` 输出）

来源脚本：`prepare_phase2_unit.py`

```json
{
  "unit_index": 5,
  "total_units": 25,
  "system_prompt": "扫描器角色 + 当前位置",
  "context": {
    "cumulative": {
      "key_facts": [],
      "state_changes": {},
      "information_revealed": []
    },
    "recent_units": []
  },
  "domain_context": null,
  "phase1_hints": null,
  "content": "当前段落文本",
  "output_format": {
    "type": "array",
    "items": {
      "rule_id": "string",
      "sentence_index": "int",
      "severity": "critical|warning|suggestion",
      "original_text": "string",
      "issue": "string",
      "suggestion": "string",
      "context_conflict": "string (optional)"
    },
    "empty_if_clean": true
  },
  "rule_batches": [
    {
      "batch_label": "critical_checks",
      "priority": "critical",
      "rules": [{ "id": "L001", "name": "...", "check_prompt": "..." }]
    },
    {
      "batch_label": "warning_checks",
      "priority": "warning",
      "rules": [...]
    },
    {
      "batch_label": "suggestion_checks",
      "priority": "suggestion",
      "rules": [...]
    }
  ]
}
```

> `rule_batches` 仅在传入 `--rules-dir` 时出现。不传时回退到手动加载所有规则。

**选择性复查**：传入 `--affected-paragraphs 3,5,7` 后，不在受影响集合中的段落返回：

```json
{ "unit_index": 2, "total_units": 25, "skip": true, "reason": "not_in_affected_set" }
```

### 3.5 Score JSON（`calculate_score.py` 输出）

来源脚本：`calculate_score.py`

```json
{
  "score": 85,
  "grade": "B",
  "deduction": 15,
  "critical_count": 2,
  "warning_count": 6,
  "suggestion_count": 0,
  "total_violations": 8
}
```

评分公式：`score = max(0, 100 - Σ(weight of primary violations))`。关联分组去重：同位置同组只计最高 severity。

### 3.6 Report JSON（`generate_report.py` 输出）

来源脚本：`generate_report.py`（聚合 violations + score + split 数据）

```json
{
  "status": "success",
  "check_summary": {
    "project": "项目名",
    "chapter": "章节标识",
    "check_mode": "full",
    "total_paragraphs": 25,
    "total_sentences": 85,
    "violations_found": 8,
    "critical_count": 2,
    "warning_count": 6,
    "suggestion_count": 0,
    "score": 85,
    "grade": "B"
  },
  "violations": [
    {
      "rule_id": "D001",
      "severity": "critical",
      "source": "deterministic",
      "location": { "paragraph": 3, "sentence": 1 },
      "issue": "...",
      "correlation_group": "readability",
      "is_primary": true
    }
  ],
  "score_breakdown": {
    "deterministic": { "failed": 5 },
    "llm": { "failed": 3 },
    "deduction": 15
  }
}
```

### 3.7 Extractions JSON（Agent LLM 产出 → `update_context.py` 输入）

来源：Agent LLM 提取（非脚本输出），写入 `$TMP/extractions.json` 后传给 `update_context.py`

```json
{
  "key_facts": [{ "fact": "...", "confidence": 0.9 }],
  "character_states": { "角色A": { "value": "受伤", "confidence": 0.85 } },
  "information_revealed": [{ "info": "...", "confidence": 0.7 }]
}
```

---

## 4. Workspace 最小要求

### 必需文件

| 文件 | 示例 | 说明 |
|------|------|------|
| `context/domain-config.yaml` | `examples/chinese-novel/context/domain-config.yaml` | 领域配置（有默认值） |
| `context/context-sources.yaml` | `examples/chinese-novel/context/context-sources.yaml` | 上下文源声明 |
| `rules/deterministic/*.yaml` | `examples/chinese-novel/rules/deterministic/` | Phase 1 确定性规则 |
| `rules/llm/*.yaml` | `examples/chinese-novel/rules/llm/` | Phase 2 LLM 规则 |

### 可选文件

| 文件 | 说明 |
|------|------|
| `rules/learned/*.yaml` | 自学习沉淀规则（status: active/experimental） |
| `rules/_index.yaml` | 规则索引 |
| `rules/replacements/` | 替换对照表（aigc-harness 使用） |

### 快速验证

```bash
python3 scripts/validate_workspace.py --workspace <workspace_path>
```

输出 JSON：
```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "info": [],
  "summary": {
    "deterministic_rules": 15,
    "llm_rules": 8
  }
}
```

验证项包括：规则 ID 重复检查、规则类型有效性、LLM 规则 `check_prompt` 必需字段、关联分组引用完整性、severity/weight 一致性。

退出码：0 = 通过，1 = 存在 error。

---

## 5. Fix Loop 编排协议

Fix Loop 由**上游 Supervisor** 编排，Scanner 只负责检查。Supervisor 协调 Scanner 和 Fix Agent 的交互。

### 5.1 调用序列

```
1. Scanner 检查 → 返回报告
2. Supervisor 判断收敛条件
3. 未收敛 → Supervisor 调用 Fix Agent 修复
4. Supervisor 识别修改段落
5. Scanner 复查 → 返回新报告
6. 重复 2-5 直到收敛或达到 max_rounds
```

### 5.2 收敛判定条件

从 `domain-config.yaml` 的 `fix_loop.convergence` 读取：

```yaml
fix_loop:
  max_rounds: 3
  convergence:
    critical: 0       # critical 违规数须为 0
    warning: 3        # warning 违规数须 <= 3
    score: 85         # 分数须 >= 85
  stagnation_delta: 2  # 分数变化 <= 2 视为停滞
```

收敛条件：`critical == 0 AND warning <= convergence.warning AND score >= convergence.score`

### 5.3 Round 2+ 选择性复查

Round 1 始终全量复查。Round 2+ 可仅复查受影响段落：

**Phase 2 选择性复查**：通过 `--affected-paragraphs` 标记修改段落（±1 邻居段）

```bash
python3 scripts/prepare_phase2_unit.py \
  --split-json $TMP/split.json \
  --context-json $TMP/context.json \
  --phase1-violations $TMP/phase1_violations.json \
  --config <workspace>/context/domain-config.yaml \
  --unit-index <N> \
  --rules-dir <workspace>/rules/llm \
  --affected-paragraphs 3,5,7
```

**评分差量合并**：通过 `--baseline-violations` + `--affected-paragraphs`

```bash
python3 scripts/calculate_score.py \
  --violations $TMP/new_violations.json \
  --config <workspace>/context/domain-config.yaml \
  --baseline-violations $TMP/prev_all_violations.json \
  --affected-paragraphs 3,5,7
```

逻辑：受影响段落使用新违规，未受影响段落保留上一轮 baseline 违规。

### 5.4 停滞 / 退化处理

| 场景 | 条件 | 处理 |
|------|------|------|
| 停滞 | `delta_score <= stagnation_delta` | 展示趋势，询问用户是否继续 |
| 退化 | `delta_score < 0` | 回滚到上一版内容，上报用户 |
| 达到上限 | `round >= max_rounds` | 上报用户决策 |

---

## 6. 错误处理与传播

### 6.1 脚本执行失败

脚本以**非零退出码 + stderr 错误信息**报告失败：

```
Exit code: 1
stderr: ERROR: Schema version mismatch. Scanner=2.1, Workspace=3.0
```

上游应：
1. 捕获退出码和 stderr
2. 向用户报告错误
3. 不重试（脚本错误通常是配置问题）

### 6.2 LLM 响应异常

Phase 2 中 LLM 可能返回非 JSON 或格式错误的响应：

| 场景 | 处理 |
|------|------|
| 非 JSON 响应 | 重试一次（同一 prompt），仍失败则跳过该段 |
| JSON 格式错误 | 重试一次，仍失败则跳过该段 |
| 空响应 | 视为无违规（`[]`） |

跳过的段应记录到错误日志，最终报告需标注哪些段被跳过。

### 6.3 部分成功场景

某些段扫描失败但其余段正常时：

1. 收集已成功的段落的违规结果
2. 跳过失败的段（不计违规，但记录错误）
3. 评分和报告基于成功扫描的段落
4. 报告中标注扫描覆盖率和跳过段落列表

### 6.4 文件系统错误

| 错误 | 处理 |
|------|------|
| `content_path` 不存在 | 立即失败，返回错误信息 |
| workspace 目录不完整 | `validate_workspace.py` 预检可提前发现 |
| 临时文件损坏 | 删除 `$TMP` 目录重试一次 |

---

## 7. 临时文件约定

### 7.1 目录结构

```
/tmp/content-scanner/
├── split.json                  # Step 1: 文本分片结果
├── phase1_violations.json      # Step 2: Phase 1 确定性违规
├── context.json                # Step 3: 累积上下文（逐段更新）
├── extractions.json            # Step 3: 当前段 LLM 提取结果
├── all_violations.json         # Step 4: Phase 1 + Phase 2 合并违规
├── score.json                  # Step 4: 评分结果
└── report.json                 # Step 5: 最终报告
```

### 7.2 文件用途

| 文件 | 写入者 | 消费者 | 说明 |
|------|--------|--------|------|
| `split.json` | `split_text.py` stdout | `prepare_phase2_unit.py`, `generate_report.py` | L1/L2 分片结构 |
| `phase1_violations.json` | `run_deterministic.py` stdout | `prepare_phase2_unit.py`, `calculate_score.py` | Phase 1 违规列表 |
| `context.json` | `update_context.py` 读写 | `prepare_phase2_unit.py` | 累积上下文（含 key_facts, state_changes 等） |
| `extractions.json` | 上游 Agent 写入 | `update_context.py` | 当前段的 LLM 提取结构化信息 |
| `all_violations.json` | 上游 Agent 合并写入 | `calculate_score.py`, `generate_report.py` | 所有违规（Phase 1 + Phase 2） |
| `score.json` | `calculate_score.py` stdout | `generate_report.py` | 评分 + 等级 |
| `report.json` | `generate_report.py` stdout | 上游 Agent / 用户 | 最终完整报告 |

### 7.3 清理建议

- 每次扫描开始前：`mkdir -p /tmp/content-scanner`（幂等）
- 扫描结束后：上游可选择保留临时文件供调试，或 `rm -rf /tmp/content-scanner` 清理
- Fix Loop 多轮间：保留每轮的 `all_violations.json` 作为下一轮的 baseline，命名为 `all_violations_round{N}.json`

---

## 参考

| 文档 | 路径 | 说明 |
|------|------|------|
| 完整协议 | `SKILL.md` | 执行工作流、触发模式、Agent Map |
| 脚本 API | `TOOLS.md` | 各脚本 CLI 参数和输出格式 |
| Agent 行为 | `AGENTS.md` | Agent 角色定义和行为准则 |
| AIGC Harness | `aigc-harness/SKILL.md` | 唯一上游消费者示例 |
| 规则格式 | `reference/rule-schema.md` | 11 种规则 type + LLM/学习规则 schema |
| 上下文结构 | `reference/context-schema.md` | 累积上下文 + domain-config 完整 schema |
| 评分算法 | `reference/scan-algorithm.md` | 两阶段扫描详细规范 |
| 示例 workspace | `examples/chinese-novel/` | 中文小说领域完整示例 |
