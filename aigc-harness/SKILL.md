---
name: aigc-harness
description: "AIGC 检测修复闭环协议（通用版）。诊断→沉淀→改写→验证 四阶段自动化闭环。支持 Claude Code 和 OpenClaw 双平台运行。"
version: "1.1.0"
owner: shared
platforms:
  - claude-code
  - openclaw
triggers:
  - direct
  - message
  - upstream
parent_skill: content-scanner
inputs:
  content_path:
    type: string
    required: true
    description: "待处理文本文件路径"
  workspace_path:
    type: string
    required: true
    description: "包含 rules/ 和 context/ 的 workspace 路径"
  external_aigc_score:
    type: number
    required: false
    description: "外部检测工具的 AIGC 分数"
  segment_range:
    type: string
    required: false
    description: "处理范围，如 '1-5' 表示前5段"
---

# AIGC Harness 协议 v1.1

## 概述

AIGC 判定→沉淀→改写→验证 四阶段自动化闭环。当内容被判定为 AI 生成或 AIGC 值高时，自动完成诊断、规则沉淀、定向改写、验证收敛。

**设计原则**：协议通用，领域参数通过 `domain-config.yaml` 的 `aigc_harness` 节注入。

## 触发条件

满足任一：
- 用户报告内容"AI味太重"/"AIGC分数太高"/"降AI味"
- 用户报告外部检测工具的 AIGC 分数
- 上游工作流触发（如 content-scanner 分数低于阈值）
- 消息触发：`aigc-check <content_path> [workspace=<w>]`

## 四阶段概览

| Phase | 名称 | 输入 | 输出 |
|-------|------|------|------|
| 1 | 诊断 | 内容路径 + (可选)外部AIGC分数 | full_report + uncovered_patterns |
| 2 | 规则沉淀 | uncovered_patterns | 候选规则 + 替换对 |
| 3 | 定向改写 | report + 新规则 + 原文 | 修订后内容 |
| 4 | 验证 + Fix Loop | 修订内容 + baseline scores | 最终结果 + 规则有效性 |

---

## 执行工作流（自包含）

### 参数约定

```
WORKSPACE   = workspace_path
DOMAIN_CFG  = $WORKSPACE/context/domain-config.yaml
CONTENT     = content_path
TMP         = /tmp/aigc-harness
```

### domain-config.yaml aigc_harness 配置

```yaml
aigc_harness:
  semantic_dimensions:
    - {name: "维度名", weight: N}
  revision_thresholds:
    rewrite: 60        # < 此值 → rewrite
    anti_detect: 70    # rewrite~此值 → anti-detect
    polish: 80         # anti_detect~此值 → polish
  convergence:
    pass_score: 75
    significant_improvement: 10
    acceptable_improvement: 5
  fix_loop:
    max_rounds: 2
    stagnation_delta: 2
  fix_agent: "agent_name"
  segment_size: 3000
```

### Phase 1: 诊断

#### 1.1 门控检测

调用 content-scanner 的 `run_deterministic.py` 快速检测：

```bash
python3 scripts/run_deterministic.py \
  --input $CONTENT --rules-dir $WORKSPACE/rules/deterministic \
  --config $DOMAIN_CFG --context-dir $WORKSPACE/context --genre <genre>
```

IF gate_report.score >= revision_thresholds.polish:
→ 提示用户"AI痕迹较低({score}分)，是否继续优化？"，等用户确认

#### 1.2 增强检测

执行完整 content-scanner 工作流（Phase 1 + Phase 2），生成 `full_report`：
- ai_trace_score (0-100)
- 确定性违规 per-segment
- 语义分析 per-segment（按 semantic_dimensions）
- 统计特征（TTR/句长std/段长std/主动句比例）
- segment_violation_map: {段序号: [违规列表]}

#### 1.3 规则覆盖分析

1. 读取 `rules/_index.yaml`
2. 对照 full_report.violations → 每个违规映射到规则 ID
3. 标记: covered（有规则覆盖）vs uncovered（无规则覆盖）
4. 对 uncovered 的语义分析发现，检查 ai-traces.yaml 替换表覆盖
5. 输出: uncovered_patterns 列表

IF uncovered_patterns 为空 → 跳过 Phase 2，直进 Phase 3

### Phase 2: 规则沉淀

> 详细协议见 `reference/precipitation.md`

前提: IF uncovered_patterns 为空 → 跳过，直进 Phase 3

#### 2.1 模式分类

对每个 uncovered_pattern 判断类型：
- 确定性模式（可用正则/统计） → 候选 D 规则
- 替换对（AI套话→人类表达） → 候选替换条目
- 语义模式（需LLM判断） → 候选 L 规则

#### 2.2 生成候选规则

- 确定性/语义 → `rules/learned/harnessed_H{NNN}.yaml`（status: experimental）
- 替换对 → 追加到 `rules/replacements/ai-traces.yaml`

#### 2.3 更新索引

- 更新 `rules/learned/_index.yaml`
- 更新 `rules/_index.md` changelog

### Phase 3: 定向改写

#### 3.1 修订模式选择

基于 ai_trace_score：
- < revision_thresholds.rewrite → rewrite（保留 30-50%）
- rewrite ~ anti_detect → anti-detect（保留 40-60%）
- anti_detect ~ polish → polish + 定点 anti-detect（保留 70%+）

基于 segment_violation_map：
- 全文低分 → 全文处理
- 局部段落低分 → 仅处理高违规 segment
- 混合 → 高违规段 rewrite，其余 polish

#### 3.2 分段处理（内容 > segment_size 时）

按 segment 拆分（每段 ~500-800字，对齐段落边界）

FOR each segment:
  调用修复 Agent({
    mode: determined_mode,
    content_path: ...,
    violations: 该segment的违规列表,
    adjacent_context: 前后各1段摘要（~100字/段）,
    new_rules: Phase 2 沉淀的规则（如有）
  }) → revised_segment

合并所有 revised_segment → 完整修订内容

#### 3.3 短内容直接处理（内容 <= segment_size）

调用修复 Agent({
  mode, violations: full_report.violations,
  new_rules: Phase 2 新规则
}) → revised_content

### Phase 4: 验证 + Fix Loop

#### 4.1 复检

对修订后内容再次执行完整 content-scanner 工作流 → post_report

#### 4.2 分数对比 + 收敛判断

```
delta = post_report.ai_trace_score - phase1_report.ai_trace_score

├── post >= pass_score AND delta >= significant_improvement → PASS（显著改善）
├── post >= pass_score AND delta >= acceptable_improvement  → PASS（可接受）
├── delta < 0                  → REGRESSION（退化，回滚原文）
└── 其他                        → 进入 Fix Loop
```

#### 4.3 Fix Loop

```
round = 1
WHILE round <= max_rounds AND post_score < pass_score:
  a. 调用修复 Agent({mode:"spot-fix", violations: 残留违规})
  b. 调用 content-scanner 快速检查 → recheck
  c. 停滞检测: delta <= stagnation_delta → 展示趋势，等用户决策
  d. 退化检测: delta < 0 → 回滚原文，上报用户
  e. round += 1
```

#### 4.4 规则有效性更新

FOR each Phase 2 新增规则:
  检查 post_report 是否仍触发该规则
  → 更新 rules/learned/ 中 effectiveness 指标

---

## 结果交付

### CLI / 文件

```
AI Trace Score: {before} → {after}
Modified segments: {N}
New rules precipitated: {N}
Rule coverage analysis: {...}
```

### 聊天摘要

```
AIGC Harness Complete: {content_id}
AI Trace: {before} → {after} (delta: +{delta})
Mode: {rewrite|anti-detect|polish}
Segments modified: {N}
New rules: {N}

{IF delta >= significant_improvement} Significantly improved.
{IF delta >= acceptable_improvement} Acceptable improvement.
{IF delta < stagnation_delta} Stagnation detected, user decision needed.
```

---

## 依赖

- **content-scanner**：Phase 1 诊断复用 `run_deterministic.py` + 语义分析
- **领域规则包**：`rules/deterministic/`、`rules/llm/`、`rules/replacements/`
- **修复 Agent**：由 `fix_agent` 配置指定

## 详细参考

| 文档 | 路径 |
|------|------|
| 上下文窗口策略 + 分段处理细节 | `reference/harness-workflow.md` |
| 规则沉淀协议 | `reference/precipitation.md` |

> 核心四阶段工作流已内联在上文。参考文档提供上下文窗口策略和深度细节。
