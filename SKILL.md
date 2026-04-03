---
name: content-scanner
description: "通用内容扫描协议（工具化版本）。确定性规则由 Python 脚本执行，Agent 只负责 Phase 2 语义判断和工具调用编排。"
version: "2.0.0"
owner: shared
---

# Content Scanner 共享协议 v2

## 概述

本 Skill 定义了一套**通用内容扫描算法框架**，通过 "共享协议 + 领域规则包" 实现跨场景复用。

**v2 核心变化**：确定性计算由 Python 脚本执行，Agent 不再心智模拟算法。

**脚本负责**：文本分割、确定性规则、上下文簿记、评分计算、报告格式化
**Agent 负责**：Phase 2 语义判断、上下文提取、自学习决策

---

## 架构：协议共享，规则注入

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

## 领域注入点

各 workspace 必须提供以下文件：

| 注入点 | 文件位置 | 说明 | 必需 |
|--------|---------|------|------|
| 确定性规则 | `rules/deterministic/*.yaml` | Phase 1 规则集 | 是 |
| LLM 规则 | `rules/llm/*.yaml` | Phase 2 规则集 | 是 |
| 规则索引 | `rules/_index.yaml` | 轻量索引（<1000 token） | 是 |
| 上下文源声明 | `context/context-sources.yaml` | 声明需要加载的上下文文件 | 是 |
| 领域配置 | `context/domain-config.yaml` | 分片参数、评分权重、Fix Loop 参数 | 是（有默认值） |
| 修复 Agent | `context/domain-config.yaml` → fix_agent | 修复动作由谁执行 | 是 |
| 学习规则 | `rules/learned/*.yaml` | 自动生成（可选） | 否 |

---

## Agent 工作流（工具调用版）

### Step 1: 文本分片

```bash
python3 {baseDir}/scripts/split_text.py \
  --input <文本文件路径> \
  --config <domain-config.yaml路径>
```

**输出**: JSON `{ l1_units, l2_units, l2_to_l1, metadata }`

### Step 2: Phase 1 确定性检查

```bash
python3 {baseDir}/scripts/run_deterministic.py \
  --input <文本文件路径> \
  --rules-dir <确定性规则目录> \
  --config <domain-config.yaml路径> \
  --context-dir <上下文目录> \
  --genre <题材>
```

**输出**: JSON `{ violations[], summary }`

包含 11 种规则类型：`pattern | patterns | density | fatigue | keyword_list | consecutive | length_check | pattern_list | consecutive_pattern | settings_gate | statistical`

### Step 3: Phase 2 逐段 LLM 深检（Agent 负责）

```
初始化累积上下文:
  exec update_context.py --init → 生成空 context.json

FOR 每个段落 (unit_index):
  1. 构建检查上下文
     - 加载领域上下文源
     - 读取 context.json 获取累积摘要
     - 如果 enable_phase1_hints=true: 过滤本段 Phase 1 违规 → hints

  2. 确定适用的 LLM 规则 (rules/llm/ + 动态规则 + 学习规则)

  3. Agent 做 LLM 语义判断（一次调用检查当前段落）

  4. Agent 写 extractions.json:
     {
       "key_facts": [{"fact": "...", "confidence": 0.9}],
       "character_states": {"角色A": {"value": "受伤", "confidence": 0.85}},
       "information_revealed": [{"info": "...", "confidence": 0.7}]
     }

  5. 更新累积上下文:
     exec update_context.py \
       --context-json /tmp/context.json \
       --extractions /tmp/extractions.json \
       --config <domain-config.yaml> \
       --context-sources <context-sources.yaml> \
       --unit-index <N> --unit-text "段落原文..."

  6. 收集 LLM 违规 → llm_violations[]
```

### Step 4: 合并违规 + 评分

```bash
# 合并 Phase 1 + Phase 2 违规到一个文件
cat /tmp/phase1_violations.json /tmp/phase2_violations.json > /tmp/all_violations.json

# 计算评分
python3 {baseDir}/scripts/calculate_score.py \
  --violations /tmp/all_violations.json \
  --config <domain-config.yaml路径>
```

**输出**: JSON `{ score, grade, deduction, critical_count, warning_count, ... }`

### Step 5: 生成报告

```bash
python3 {baseDir}/scripts/generate_report.py \
  --violations /tmp/all_violations.json \
  --score /tmp/score.json \
  --split /tmp/split.json \
  --config <domain-config.yaml路径> \
  --project <项目名> --content-id <章节标识>
```

**输出**: 完整检查报告 JSON

---

## 脚本目录

```
.openclaw/skills/content-scanner/scripts/
├── requirements.txt          # pyyaml, jieba
├── lib/
│   ├── __init__.py
│   ├── text_utils.py         # L1/L2 文本分割
│   ├── rule_loader.py        # YAML 规则加载 + type 分派
│   ├── context_manager.py    # 累积上下文管理
│   ├── scoring.py            # 评分 + 关联分组去重
│   └── report.py             # 报告 JSON 组装
├── split_text.py             # CLI: 文本分片
├── run_deterministic.py      # CLI: Phase 1 全部确定性规则
├── update_context.py         # CLI: 累积上下文更新
├── calculate_score.py        # CLI: 评分计算
└── generate_report.py        # CLI: 报告生成
```

---

## 参数化接口

所有参数有默认值，可由领域配置覆盖。完整 schema → `reference/context-schema.md`

```yaml
domain_config:
  text_units:
    l1_separator: "。！？"
    l2_separator: "\\n"
    scan_unit: "l2"
    locate_unit: "l1"

  context:
    recent_window: 3
    max_key_facts: 50
    max_information: 30
    emotional_sample_rate: 3
    enable_phase1_hints: true

  scoring:
    critical_weight: 10
    warning_weight: 3
    suggestion_weight: 1
    grade_thresholds:
      A: { min_score: 90, max_critical: 0, max_warning: 3 }
      B: { min_score: 80, max_critical: 0, max_warning: 5 }
      C: { min_score: 70, max_critical: 2 }
      D: { min_score: 0, max_critical: 999 }
    correlation_groups:
      setting_integrity: []
      character_behavior: []
      readability: []

  fix_loop:
    max_rounds: 3
    convergence:
      critical: 0
      warning: 3
      score: 85
    stagnation_delta: 2

  self_learning:
    upgrade_threshold: { times_applied: 10, effectiveness: 0.5 }
    downgrade_threshold: { false_positive_rate: 0.3, times_applied: 5 }
```

---

## 规则文件格式

所有规则遵循统一 YAML schema。详细规范 → `reference/rule-schema.md`

### 确定性规则 type 映射

| type | 规则 | 脚本实现 |
|------|------|---------|
| `pattern` | D001, D002 | 单正则匹配 |
| `patterns` | D003 | 多正则列表，任一匹配触发 |
| `density` | D004 | 词频计数 vs 密度阈值 |
| `fatigue` | D005 | 按 genre_profiles 选词表，每词≤1次 |
| `keyword_list` | D006, D007 | 关键词计数，全章≤1次 |
| `pattern_list` | D008, D011 | 多正则组合匹配 |
| `consecutive` | D009 | 连续句子含目标字符计数 |
| `length_check` | D010 | 段落字数 > 阈值计数 |
| `consecutive_pattern` | D012 | 段落开头模式重复 |
| `settings_gate` | D013-D015 | 读 settings_release.json + 关键词匹配 |
| `statistical` | D016-D019 | TTR/句长std/段长std/主动句比例 |

### LLM 规则

```yaml
id: L{NNN}
name: "规则名称"
severity: critical|warning|suggestion
weight: {N}
phase: 2
check_prompt: |
  LLM 检查逻辑描述
applies_to: [all|dialogue|action|description]
```

### 学习规则

```yaml
id: R-L{NNN}
name: "规则名称"
source: human_feedback
created_from: "feedback/FB-{YYYY}-{NNN}"
severity: warning
pattern_type: structural|semantic|contextual
check_prompt: |
  检查逻辑描述
status: experimental
effectiveness:
  times_applied: 0
  times_caught: 0
  false_positive_count: 0
  false_positive_rate: null
```

---

## 自学习机制

从人工反馈中自动学习。详细规范 → `reference/self-learning.md`

| 反馈类型 | 触发动作 |
|---------|---------|
| FALSE_POSITIVE | 规则 false_positive_count++；率 > 阈值 → 降级 |
| MISSED_ISSUE | LLM 提取模式 → 生成候选规则 → 存入 rules/learned/ |
| FIX_APPROVED | 规则 times_caught++；强化规则权重 |

**生命周期**: `experimental → review_pending → active → review_needed → deprecated`

---

## Fix Loop 模式

由 Supervisor 编排，Scanner 只负责检查。

```
Round 1: Scanner 检查 → 有违规 → Supervisor 协调修复 Agent
Round 2: Scanner 复查 → 仍有违规 → Supervisor 协调修复 Agent
         停滞检测: Round2 分数 - Round1 分数 ≤ stagnation_delta → 提示用户
Round 3: Scanner 复查 → 仍有违规 → 上报用户决策

收敛条件: critical == 0 AND warning ≤ {convergence.warning} AND score ≥ {convergence.score}
```

---

## 评分系统

100 分制，含关联分组去重。

```
得分 = 100 - Σ(max(v.weight for v in correlation_group))

同位置 (paragraph, sentence) 的违规按 correlation_group 分组，
每组只计最高 severity 的违规。
无 correlation_group 的违规独立计分。
```

---

## 输出格式

### 检查报告 JSON

```json
{
  "status": "success",
  "check_summary": {
    "project": "项目名",
    "chapter": "章节/文章标识",
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
      "rule_name": "规则名称",
      "location": { "paragraph": 12, "sentence": 3 },
      "original_text": "原文片段",
      "severity": "critical",
      "weight": 10,
      "issue": "问题描述",
      "suggestion": "修改建议",
      "source": "deterministic|llm|learned",
      "correlation_group": "setting_integrity|null",
      "is_primary": true
    }
  ],
  "score_breakdown": {
    "deterministic": { "failed": 4 },
    "llm": { "failed": 4 },
    "deduction": 15
  }
}
```

---

## 关键参考

| 文档 | 路径 | 说明 |
|------|------|------|
| 扫描算法详规 | `reference/scan-algorithm.md` | 两阶段算法详细流程 |
| 规则格式规范 | `reference/rule-schema.md` | 确定性/LLM/学习规则 YAML schema |
| 上下文结构规范 | `reference/context-schema.md` | 累积上下文结构 + domain-config schema |
| 自学习规范 | `reference/self-learning.md` | 反馈处理 + 规则生命周期 |
| 共享工具定义 | `reference/tools-common.md` | 9 个领域无关工具的完整定义 |
