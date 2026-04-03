# 自学习机制规范

## 概述

Content Scanner 内置自学习机制，从人工反馈中自动生成和调整检查规则，无需手动编写新规则。

---

## 三种反馈类型

### FALSE_POSITIVE（误报）

Scanner 报告了问题，但人工审核认为不是问题。

**处理流程**:
1. 规则 `false_positive_count += 1`
2. 更新规则有效率: `effectiveness = times_caught / times_applied`
3. IF `false_positive_rate > downgrade_threshold.false_positive_rate` AND `times_applied >= downgrade_threshold.times_applied`:
   - 规则降级为 `experimental`
   - 如果关联知识库条目 → 输出 feedback (effective=false)

### MISSED_ISSUE（漏报）

Scanner 未报告问题，但人工检查发现应捕获的问题。

**处理流程**:
1. LLM 分析漏报问题，提取通用模式（1 次 LLM 调用）
2. 生成候选规则（id: R-L{NNN}）
3. 标记为 `experimental`
4. 存入 `rules/learned/`
5. 更新 `rules/learned/_index.yaml`

**模式提取 Prompt**:
```
分析以下漏报问题，提取可复用的检查规则：
- 漏报单元: {unit_text}
- 问题描述: {human_description}
- 上下文: {surrounding_units}

请提取:
1. 问题模式（通用化描述）
2. 检查逻辑（如何识别这类问题）
3. 严重级别建议
4. 适用场景
```

### FIX_APPROVED（修复确认）

Scanner 报告的问题被确认正确，修改建议被采纳。

**处理流程**:
1. 规则 `times_caught += 1`
2. 更新规则有效率
3. 如果关联知识库条目:
   - 输出 feedback (effective=true)
   - Supervisor 路由到知识库管理 Agent

---

## 规则生命周期

```
  ┌─────────────┐     应用≥阈值      ┌───────────────┐     人工审核通过     ┌──────────┐
  │ experimental├───────────────────►│ review_pending ├───────────────────►│  active   │
  │  (实验性)    │   有效率≥阈值       │  (待人工审核)    │                    │  (活跃)    │
  └──────┬──────┘                   └───────┬───────┘     ┌─────────────┐ └─────┬─────┘
       ▲  ▲                                 │             │             │       │
       │  │                         审核不通过 │             │ 误报率>阈值   │       │
       │  │                                 ▼             │             │       │
       │  │                           ┌──────────┐        │             │       │
       │  └───────────────────────────┤deprecated│◄───────┘             │       │
       │        重新验证               │ (已废弃)  │                      │       │
       │                              └──────────┘    ┌─────────────────┘       │
       │                                              │ 审核通过                  │
       │                                              ▼                          │
       │                                       ┌──────────────┐               │
       └───────────────────────────────────────│review_needed │───────────────┘
              重新实验                           │ (降级待审核)  │  审核不通过
                                                └──────┬───────┘
                                                       │ 审核不通过
                                                       ▼
                                                ┌──────────┐
                                                │deprecated│
                                                │ (已废弃)  │
                                                └──────────┘
```

### 状态转换条件

| 转换 | 条件 | 默认阈值 |
|------|------|---------|
| experimental → review_pending | times_applied ≥ 10 AND effectiveness ≥ 50% | 由 domain-config.self_learning.upgrade_threshold 定义 |
| review_pending → active | 人工审核通过 | - |
| review_pending → deprecated | 人工审核不通过 | - |
| review_pending → experimental | 人工要求重新验证（重置 times_applied） | - |
| active → review_needed | false_positive_rate > 30% AND times_applied ≥ 5 | 由 domain-config.self_learning.downgrade_threshold 定义 |
| review_needed → deprecated | 人工审核不通过 | - |
| review_needed → active | 人工审核通过 | - |
| deprecated → experimental | 重新启用（人工操作） | - |

### review_pending 状态行为

- 仍然参与检查（与 experimental 相同行为）
- 产生的 violation 标记 `source: "learned_review_pending"`
- **不影响正式评分**（仅记录，不扣分）
- 出现在检查报告的单独 section: `pending_review_violations`
- 等待人工批量审核

### 批量审核机制

审核者可一次处理多条 review_pending 规则:

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

---

## 反馈记录格式

每条反馈存储在各 workspace 的 `feedback/_log.md`:

```markdown
### FB-{YYYY}-{NNN}

- **日期**: YYYY-MM-DD
- **内容标识**: 章节/文章标题
- **反馈类型**: FALSE_POSITIVE | MISSED_ISSUE | FIX_APPROVED
- **关联规则**: {rule_id}
- **人工标注**:
  - 原文: "..."
  - 标注说明: "..."
- **处理结果**: 待处理 / 已处理
- **规则变更**: (处理后的变更记录)
```

---

## 候选规则生成模板

```yaml
id: R-L{NNN}  # 自动递增
name: "从反馈提取的规则名称"
source: human_feedback
created_from: "feedback/FB-{YYYY}-{NNN}"
created_at: "{timestamp}"
severity: warning  # 默认 warning
pattern_type: structural|semantic|contextual
check_prompt: |
  {LLM 提取的检查逻辑描述}
applies_to: [all]
status: experimental
effectiveness:
  times_applied: 0
  times_caught: 0
  false_positive_count: 0
  false_positive_rate: null
```

---

## 批量反馈处理

支持一次提交多条反馈：

```json
{
  "feedback_batch": [
    {
      "content_id": "内容标识",
      "type": "FALSE_POSITIVE",
      "rule_id": "D004",
      "original_text": "...",
      "note": "说明"
    },
    {
      "content_id": "内容标识",
      "type": "MISSED_ISSUE",
      "unit_index": 12,
      "original_text": "...",
      "issue_description": "问题描述",
      "severity_suggestion": "warning"
    }
  ]
}
```
