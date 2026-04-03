# 共享工具定义

> 领域无关的 9 个工具，所有使用 content-scanner 协议的 workspace 共享。
> 各 workspace 在自身 TOOLS.md 中引用本文件，并补充领域特有工具。

---

## Phase 1 工具：确定性规则引擎

### 1. split_text - 文本分片

将待检查文本拆分为多级结构。

**输入**: 原始文本 + domain-config.text_units 参数
**输出**:

```json
{
  "l1_units": [
    { "index": 0, "text": "...", "parent_index": 0 }
  ],
  "l2_units": [
    { "index": 0, "text": "...", "child_indices": [0, 1, 2], "char_count": 85 }
  ],
  "metadata": {
    "total_chars": 2500,
    "total_l1": 85,
    "total_l2": 25
  }
}
```

**分片规则**（可覆盖）:
- L1: 以 `l1_separator` 分割（默认 `。！？`，保留标点）
- L2: 以 `l2_separator` 分割（默认 `\n`）
- 过滤标题行（由领域配置决定过滤规则）

### 2. run_deterministic_rules - 确定性规则批量检查

对每个 L1 单元执行全部确定性规则。

**输入**: L1/L2 结构 + 规则列表
**输出**: `deterministic_violations[]`

每条违规:
```json
{
  "rule_id": "D001",
  "rule_name": "规则名称",
  "location": { "paragraph": 5, "sentence": 2 },
  "original_text": "原文片段",
  "severity": "critical",
  "weight": 10,
  "message": "违规描述"
}
```

### 3. calculate_statistics - 统计特征计算

计算全文级统计指标（用于确定性规则中的统计类检查）。

**通用特征**:

| 特征 | 计算 |
|------|------|
| TTR | 不重复词数 / 总词数 |
| 单元长度标准差 | L1 单元字数的标准差 |
| 段落长度标准差 | L2 单元字数的标准差 |

各领域可添加领域特有统计特征。

---

## Phase 2 工具：逐段 LLM 深检

### 6. run_llm_check_per_unit - 逐段 LLM 检查

对单个 L2 单元执行一次 LLM 调用，检查所有适用规则。

**输入**:
- 当前单元文本
- 累积上下文
- 适用的规则列表
- 单元索引
- phase1_hints: 本单元的 Phase 1 违规摘要（可选，默认 []）
- focus_areas: 基于 phase1_hints 推导的建议关注领域（可选，默认 []）

**LLM Prompt 结构**:

```
[System] 你是内容扫描器，正在检查第{N}段/节。
当前单元索引: {P}/{total}
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

**输出**: `llm_violations[]`

### 7. update_context - 更新累积上下文

每段检查完后，从该段提取信息更新累积上下文。支持置信度追踪和矛盾纠错。

**提取内容**（领域相关字段名不同，逻辑相同）:
- 新出现的关键事实（附带 confidence score）
- 状态变更（附带 confidence score）
- 新揭示的信息（附带 confidence score）
- 曲线采样点
- 更新滑动窗口

**置信度处理**:
- confidence < tentative_threshold 的提取标记为 `tentative`
- 后续高置信度矛盾提取可覆盖 tentative 条目（correction_strategy: override）
- 非矛盾信息正常追加

**提取输出格式**（带置信度的条目）:
```json
{
  "fact": "角色A表现愤怒",
  "confidence": 0.85,
  "tentative": false,
  "source_paragraph": 5
}
```

---

## 评分与报告

### 8. calculate_check_score - 计算检查得分

100 分制，含关联分组去重。

**去重逻辑**:
1. 同一位置 (paragraph, sentence) 的违规按 `correlation_group` 分组
2. 每个 correlation_group 内只计最高 severity 的违规（标记 `is_primary: true`）
3. 无 correlation_group 的违规独立计分

```
grouped = group_violations(all_violations, correlation_mapping)
score = 100 - Σ(max(v.weight for v in group))  // 每组只计最高

等级: 由 domain-config.scoring.grade_thresholds 定义
默认:
- A (90-100): 无 critical，warning ≤ 3
- B (80-89): 无 critical，warning ≤ 5
- C (70-79): critical ≤ 2
- D (<70): critical > 2

权重: 由 domain-config.scoring 定义
- critical: 默认 10 分/次
- warning: 默认 3 分/次
- suggestion: 默认 1 分/次（不扣分，仅记录）
```

### 9. generate_check_report - 生成检查报告

输出完整检查报告 JSON。

**输出结构**:

```json
{
  "status": "success",
  "check_summary": {
    "project": "项目名",
    "content_id": "内容标识",
    "check_mode": "full",
    "total_units": 25,
    "total_sub_units": 85,
    "total_rules_applied": 45,
    "violations_found": 8,
    "critical_count": 2,
    "warning_count": 6,
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
    "deterministic": { "passed": 21, "failed": 4 },
    "llm": { "passed": 17, "failed": 4 }
  },
  "sync_hint": { "type": "scanner_report", "files": [] }
}
```

---

## 自学习工具

### 10. process_human_feedback - 处理人工反馈

分析三种反馈类型并触发相应动作。

**输入**:
- feedback_id: 反馈记录 ID
- feedback_type: FALSE_POSITIVE | MISSED_ISSUE | FIX_APPROVED
- original_report: 原始检查报告
- human_annotation: 人工标注内容

**处理逻辑**:

| 反馈类型 | 动作 |
|---------|------|
| FALSE_POSITIVE | 规则 false_positive_count++；若率超阈值 → 降级 |
| MISSED_ISSUE | LLM 提取模式 → 生成候选规则 → 存入 rules/learned/ |
| FIX_APPROVED | 规则 times_caught++；强化权重 |

### 批量审核（review_pending 规则）

当学习规则达到升级阈值后自动进入 `review_pending` 状态。
审核者可通过批量审核接口一次性处理:

```json
{
  "review_action": "batch_review",
  "reviews": [
    { "rule_id": "R-L003", "action": "approve", "note": "模式有效" },
    { "rule_id": "R-L005", "action": "reject", "note": "过于宽泛" },
    { "rule_id": "R-L006", "action": "retest", "note": "需更多数据" }
  ]
}
```

action 类型:
- **approve**: review_pending → active
- **reject**: review_pending → deprecated
- **retest**: review_pending → experimental（重置 times_applied）

### 11. generate_candidate_rule - 从漏报提取候选规则

当 MISSED_ISSUE 发生时，用 LLM 分析漏报问题，提取通用模式。

**输入**: 漏报的单元原文 + 问题描述 + 上下文
**输出**: 候选规则 YAML

```yaml
id: R-L{NNN}
name: "规则名称"
source: human_feedback
created_from: "feedback/FB-{YYYY}-{NNN}"
severity: warning
pattern_type: structural|semantic|contextual
check_prompt: |
  检查逻辑描述
applies_to: [all]
status: experimental
effectiveness:
  times_applied: 0
  times_caught: 0
  false_positive_rate: null
```
