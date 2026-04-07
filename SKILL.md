---
name: content-scanner
description: "通用内容扫描协议 v2.1。确定性规则由 Python 脚本执行，Agent 只负责 Phase 2 语义判断和工具调用编排。支持 Claude Code 和 OpenClaw 双平台运行。"
version: "2.1.0"
owner: shared
platforms:
  - claude-code
  - openclaw
triggers:
  - direct
  - message
  - heartbeat
  - upstream
inputs:
  content_path:
    type: string
    required: true
    description: "待扫描文本文件路径"
  workspace_path:
    type: string
    required: true
    description: "包含 rules/ 和 context/ 的 workspace 路径"
  genre:
    type: string
    required: false
    default: "general"
  check_mode:
    type: string
    required: false
    default: "full"
    enum: ["full", "quick"]
  content_id:
    type: string
    required: false
    description: "内容标识（章节名/文章标题）"
---

# Content Scanner 共享协议 v2.1

## 概述

通用内容扫描框架，"共享协议 + 领域规则包" 实现跨场景复用。

**脚本负责**：文本分割、确定性规则、上下文簿记、评分计算、报告格式化
**Agent 负责**：Phase 2 语义判断、上下文提取、自学习决策

**平台兼容**：协议定义 WHAT（做什么），平台定义 HOW（怎么做）。Python 脚本是共享执行层。

---

## 架构

```
┌──────────────────────────────────────────────┐
│         content-scanner（共享协议）            │
│                                              │
│  ┌─────────────┐  ┌──────────────────────┐   │
│  │ 脚本工具     │  │ 自学习引擎           │   │
│  │ Phase 1     │  │ 反馈 → 规则生成      │   │
│  │ 评分/报告   │  │ 生命周期管理         │   │
│  └──────┬──────┘  └──────────┬───────────┘   │
│         │                    │               │
│         ▼                    ▼               │
│  ┌──────────────────────────────────────┐    │
│  │          规则注入点（interface）       │    │
│  │  - rules/deterministic/              │    │
│  │  - rules/llm/                        │    │
│  │  - context_sources: {...}            │    │
│  │  - fix_agent: agent_name             │    │
│  │  - scoring_weights: {...}            │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

---

## 触发模式

### Direct（直接调用）

用户提供 `content_path` 和 `workspace_path`，Agent 立即执行扫描。

### Message（消息触发）

通过聊天平台（WhatsApp/Telegram/Slack 等）发送消息触发。消息格式：

```
scan <content_path> [workspace=<workspace_path>] [genre=<genre>] [mode=<full|quick>]
```

Agent 解析参数后执行扫描，结果以聊天摘要格式回复。

### Heartbeat（定时扫描）

OpenClaw heartbeat 调度器定时读取 `HEARTBEAT.md` 中的扫描目标，自动执行。仅在分数低于阈值或有新 critical 违规时通知用户。

### Upstream（上游触发）

其他 skill（如 `aigc-harness`）作为子流程调用 content-scanner。

---

## 执行工作流（自包含）

### 前置条件

- Python 3.10+
- 依赖：`pip install pyyaml jieba`
- workspace 目录包含：`rules/deterministic/`, `rules/llm/`, `context/domain-config.yaml`, `context/context-sources.yaml`

### 参数约定

```
SCRIPTS_DIR = <项目根>/scripts
WORKSPACE   = workspace_path
DOMAIN_CFG  = $WORKSPACE/context/domain-config.yaml
CTX_SOURCES = $WORKSPACE/context/context-sources.yaml
RULES_DIR   = $WORKSPACE/rules/deterministic
CONTENT     = content_path
TMP         = /tmp/content-scanner
```

### Step 1: 文本分片

```bash
python3 $SCRIPTS_DIR/split_text.py \
  --input $CONTENT \
  --config $DOMAIN_CFG
```

输出 JSON 保存为 `$TMP/split.json`：
```json
{ "l1_units": [...], "l2_units": [...], "l2_to_l1": {...}, "metadata": {...} }
```

### Step 2: Phase 1 确定性检查

```bash
python3 $SCRIPTS_DIR/run_deterministic.py \
  --input $CONTENT \
  --rules-dir $RULES_DIR \
  --config $DOMAIN_CFG \
  --context-dir $WORKSPACE/context \
  --genre <genre>
```

输出 JSON 保存为 `$TMP/phase1_violations.json`：
```json
{
  "violations": [{
    "rule_id": "D{NNN}",
    "rule_name": "规则名称",
    "location": { "paragraph": P, "sentence": S },
    "original_text": "原文片段",
    "severity": "critical|warning|suggestion",
    "weight": N,
    "issue": "违规描述",
    "source": "deterministic"
  }],
  "summary": { ... }
}
```

### Step 3: Phase 2 逐段 LLM 深检

#### 3a. 初始化累积上下文

```bash
python3 $SCRIPTS_DIR/update_context.py \
  --init \
  --context-json $TMP/context.json \
  --extractions /dev/null \
  --config $DOMAIN_CFG \
  --context-sources $CTX_SOURCES \
  --unit-index 0
```

#### 3b. 逐段循环

读取 `$TMP/split.json` 获取 `l2_units` 总数 N，对每个 `unit_index` (0..N-1) 执行：

**i. 组装检查 prompt**

```bash
python3 $SCRIPTS_DIR/prepare_phase2_unit.py \
  --split-json $TMP/split.json \
  --context-json $TMP/context.json \
  --phase1-violations $TMP/phase1_violations.json \
  --config $DOMAIN_CFG \
  --unit-index <N> \
  --rules-dir $WORKSPACE/rules/llm \
  --learned-dir $WORKSPACE/rules/learned
```

输出 prompt 结构（含规则分批）：
```json
{
  "system_prompt": "扫描器角色 + 当前位置",
  "context": "累积上下文（关键事实+状态+已知信息+最近单元）",
  "domain_context": "领域上下文源内容",
  "phase1_hints": "Phase 1 提示（仅当该单元有违规时）",
  "content": "当前待检查段落文本",
  "output_format": "JSON 数组格式要求",
  "rule_batches": [
    {"batch_label": "critical_checks", "priority": "critical", "rules": [{id, name, check_prompt}]},
    {"batch_label": "warning_checks", "priority": "warning", "rules": [...]},
    {"batch_label": "suggestion_checks", "priority": "suggestion", "rules": [...]}
  ]
}
```

> 注：`rule_batches` 仅在传入 `--rules-dir` 时出现。旧 Agent 不传此参数时输出格式不变（向后兼容）。

**ii. Agent 执行 LLM 语义判断（分批协议）**

当输出包含 `rule_batches` 时，按批次执行 LLM 检查：

```
FOR each batch in rule_batches:
  1. 使用 batch.rules 中的规则检查当前段落
  2. 返回该批次的违规 JSON 数组
  3. 如果 skip_lower_priority_on_critical=true 且当前批次发现 critical 违规：
     → 可跳过后续低优先级批次（优化）
  4. 收集所有批次违规到 llm_violations[]
```

当 `rule_batches` 不存在时（向后兼容），回退到加载所有规则一次检查：
- `rules/llm/*.yaml` 中的 LLM 规则
- `rules/learned/*.yaml` 中 status 为 active 的学习规则

LLM Prompt 模板：

```
[System] 你是内容扫描器，正在检查第{unit_index}段/节。
当前单元索引: {unit_index+1}/{total}
你需要检查以下规则: {rule_list_with_descriptions}

[Context]
前文关键事实: {cumulative.key_facts}  // tentative 条目标注 [临时]
状态追踪: {cumulative.state_changes}    // tentative 条目标注 [临时]
已知信息边界: {cumulative.information_revealed}  // tentative 条目标注 [临时]
前序单元（最近{window}个）: {recent_units}

[Domain Context]
{领域上下文源内容}

[Phase 1 Hints] （可选，仅当本单元有 Phase 1 违规时出现）
本单元在 Phase 1 中检测到以下问题（供参考，避免重复报告相同问题）:
{phase1_hints_summary}
建议重点关注: {focus_areas}

[Content] 需要检查的内容:
{unit_text}

[Output Format] 返回 JSON 数组:
[
  {
    "rule_id": "{规则ID}",
    "sentence_index": S,
    "severity": "critical|warning|suggestion",
    "original_text": "原文片段",
    "issue": "问题描述",
    "suggestion": "修改建议",
    "context_conflict": "与前文的冲突说明（如有）"
  }
]
如果没有违规，返回空数组 []。
```

**iii. 解析 LLM 响应**

LLM 返回 JSON 数组（违规列表）。收集到 `llm_violations[]`。

如果响应不是有效 JSON，重试一次。

**iv. 提取上下文信息并更新**

Agent 从段落中提取结构化信息，写入 `$TMP/extractions.json`：
```json
{
  "key_facts": [{"fact": "...", "confidence": 0.9}],
  "character_states": {"角色A": {"value": "受伤", "confidence": 0.85}},
  "information_revealed": [{"info": "...", "confidence": 0.7}]
}
```

然后更新累积上下文：
```bash
python3 $SCRIPTS_DIR/update_context.py \
  --context-json $TMP/context.json \
  --extractions $TMP/extractions.json \
  --config $DOMAIN_CFG \
  --context-sources $CTX_SOURCES \
  --unit-index <N> \
  --unit-text "<当前段落文本>"
```

#### 上下文增长控制

| 字段 | 默认上限 | 控制策略 |
|------|---------|---------|
| key_facts | 50 条 | 超限压缩旧条目，每条附带 confidence + tentative 标记 |
| state_changes | 无上限 | 只保留最新状态，每项附带 confidence + tentative 标记 |
| information_revealed | 30 条 | FIFO，每条附带 confidence + tentative 标记 |
| recent_units | 3 个 | 滑动窗口 |

### Step 4: 合并违规 + 评分

合并 Phase 1 和 Phase 2 违规到 `$TMP/all_violations.json`：
```bash
python3 $SCRIPTS_DIR/calculate_score.py \
  --violations $TMP/all_violations.json \
  --config $DOMAIN_CFG
```

输出保存为 `$TMP/score.json`：
```json
{
  "score": 85, "grade": "B", "deduction": 15,
  "critical_count": 2, "warning_count": 6,
  "suggestion_count": 0, "total_violations": 8
}
```

评分公式：`score = 100 - Σ(weight of primary violations)`

关联分组去重：同一位置相关类别的违规归入同一 `correlation_group`，组内只计最高 severity。

### Step 5: 生成报告

```bash
python3 $SCRIPTS_DIR/generate_report.py \
  --violations $TMP/all_violations.json \
  --score $TMP/score.json \
  --split $TMP/split.json \
  --config $DOMAIN_CFG \
  --project <project_name> \
  --content-id <content_id>
```

输出完整报告 JSON：
```json
{
  "status": "success",
  "check_summary": {
    "project": "项目名", "chapter": "章节标识",
    "check_mode": "full", "total_paragraphs": 25,
    "total_sentences": 85, "violations_found": 8,
    "critical_count": 2, "warning_count": 6,
    "suggestion_count": 0, "score": 85, "grade": "B"
  },
  "violations": [...],
  "score_breakdown": { "deterministic": {...}, "llm": {...}, "deduction": 15 }
}
```

---

## 结果交付

### CLI / 文件

完整 JSON 报告输出到 stdout，可重定向到文件。

### 聊天摘要（消息/Heartbeat 触发）

```
Content Scan: {content_id}
Grade: {grade} | Score: {score}/100
Critical: {N} | Warning: {N} | Suggestion: {N}

Top Issues:
1. [{severity}] {rule_name}: {issue} (para {P})
2. [{severity}] {rule_name}: {issue} (para {P})
...

Full report: {report_path}
```

### 通知规则

- **始终通知**：新 critical 违规、等级下降 2+ 级
- **抑制通知**：分数 >= 阈值且无新违规（heartbeat 模式）
- **询问用户**：停滞时（delta <= stagnation_delta）

---

## Fix Loop

由 Supervisor 编排，Scanner 只负责检查。

```
收敛条件: critical == 0 AND warning <= {convergence.warning} AND score >= {convergence.score}

Round 1: Scanner 检查 → 有违规 → Supervisor 协调修复 Agent
Round 2: Scanner 复查 → 仍有违规 → Supervisor 协调修复 Agent
         停滞检测: Round2 分数 - Round1 分数 <= stagnation_delta → 提示用户
Round 3+: 上报用户决策

最大轮次: fix_loop.max_rounds（默认 3）
```

---

## LLM 集成契约

协议不绑定特定 LLM 模型或 API。平台需提供：

1. **结构化 prompt 调用**：能将 6 部分 prompt 结构发送给 LLM
2. **JSON 数组解析**：能解析 LLM 返回的违规 JSON 数组
3. **YAML 规则加载**：能读取 `rules/llm/*.yaml` 中的规则定义
4. **上下文提取**：能从段落中提取 key_facts、character_states、information_revealed

各平台实现方式：
- **Claude Code**：原生 LLM 推理 + Bash 工具执行脚本
- **OpenClaw**：使用配置的 LLM provider + shell 工具执行脚本

---

## Agent Map

| Step | Agent Action | Script | Output |
|------|-------------|--------|--------|
| 1 | 文本分片 | `split_text.py --input --config` | `{l1_units, l2_units, metadata}` |
| 2 | Phase 1 确定性检查 | `run_deterministic.py --input --rules-dir --config --genre` | `{violations[], summary}` |
| 3 | Phase 2 逐段 LLM 深检 | Agent LLM 分批判断 + `prepare_phase2_unit.py --rules-dir` + `update_context.py` | `llm_violations[]` |
| 4 | 合并违规 + 评分 | `calculate_score.py --violations --config` | `{score, grade, deduction}` |
| 5 | 生成报告 | `generate_report.py --violations --score --split --config` | 完整报告 JSON |

---

## 领域注入点

各 workspace 必须提供以下文件：

| 注入点 | 文件位置 | 必需 |
|--------|---------|------|
| 确定性规则 | `rules/deterministic/*.yaml` | 是 |
| LLM 规则 | `rules/llm/*.yaml` | 是 |
| 规则索引 | `rules/_index.yaml` | 是 |
| 上下文源声明 | `context/context-sources.yaml` | 是 |
| 领域配置 | `context/domain-config.yaml` | 是（有默认值） |
| 修复 Agent | `context/domain-config.yaml` → fix_agent | 是 |
| 学习规则 | `rules/learned/*.yaml` | 否 |

可运行示例 → `examples/chinese-novel/`

---

## 脚本目录

| 脚本 | 用途 |
|------|------|
| `scripts/split_text.py` | L1/L2 文本分片 |
| `scripts/run_deterministic.py` | Phase 1 全部确定性规则 |
| `scripts/prepare_phase2_unit.py` | Phase 2 单元 prompt 组装 |
| `scripts/update_context.py` | 累积上下文更新 |
| `scripts/calculate_score.py` | 评分 + 关联分组去重 |
| `scripts/generate_report.py` | 报告 JSON 组装 |

依赖：`pyyaml`, `jieba`

---

## 关键参考

| 文档 | 路径 |
|------|------|
| 规则格式规范（11 种 type + LLM/学习规则 schema） | `reference/rule-schema.md` |
| 上下文结构 + domain-config 完整 schema | `reference/context-schema.md` |
| 自学习机制（反馈处理 + 规则生命周期） | `reference/self-learning.md` |
| 脚本 API（v1 工具 → v2 脚本映射） | `reference/tools-common.md` |

> 核心工作流已内联在上文"执行工作流"中。参考文档提供边界情况和深度细节。
