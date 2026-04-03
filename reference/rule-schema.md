# 规则文件格式规范

## 概述

Content Scanner 的规则分为三类，统一使用 YAML 格式。各领域 workspace 在 `rules/` 下提供具体规则内容。

---

## 规则索引 (`rules/_index.yaml`)

轻量索引文件，始终加载（<1000 token）。

```yaml
total_rules: N
phases:
  deterministic: N  # Phase 1
  llm: N            # Phase 2

categories:
  category_name: [D001, D002, ...]

severity_distribution:
  critical: [...]
  warning: [...]

# 动态规则（运行时加载）
dynamic_rules: []    # 知识库/技巧库匹配

# 学习规则（从反馈自动生成）
learned_rules: []    # 运行时从 rules/learned/_index.yaml 加载

# 规则文件映射
file_map:
  deterministic:
    D001-D003: rules/deterministic/D001-D003-category.yaml
  llm:
    L001-L005: rules/llm/L001-L005-category.yaml
```

---

## 确定性规则 (`rules/deterministic/*.yaml`)

Phase 1 规则，不调用 LLM。

```yaml
# 单条规则
- id: D{NNN}
  name: "规则名称"
  severity: critical|warning|suggestion
  weight: N          # 扣分权重
  phase: 1
  check_type: regex|frequency|structure|statistics|cross_reference
  check_logic: |
    正则表达式或检查逻辑描述
  threshold: null    # 统计类规则的阈值
  applies_to: [all]  # 适用场景标签
  correlation_group: null  # 可选，关联分组标识（用于评分去重）
  effectiveness:
    times_applied: 0
    times_caught: 0
    false_positive_count: 0
```

### check_type 说明

| 类型 | 说明 | 示例 |
|------|------|------|
| regex | 正则匹配 | 禁止句式、标点规范 |
| frequency | 词频统计 vs 阈值 | 转折词密度、疲劳词 |
| structure | 段落级结构检查 | 段落过长、重复开头 |
| statistics | 全文统计特征 | TTR、句长标准差 |
| cross_reference | 与上下文源交叉比对 | 设定门控、术语一致性 |

---

## LLM 规则 (`rules/llm/*.yaml`)

Phase 2 规则，通过 LLM 逐段检查。

```yaml
# 单条规则
- id: L{NNN}
  name: "规则名称"
  severity: critical|warning|suggestion
  weight: N
  phase: 2
  check_prompt: |
    LLM 检查逻辑描述。
    应包含: 检查什么、什么算违规、严重级别判断标准。
  applies_to: [all]
  correlation_group: null  # 可选，关联分组标识（用于评分去重）
  effectiveness:
    times_applied: 0
    times_caught: 0
    false_positive_count: 0
```

### check_prompt 编写指南

好的 check_prompt 应该：
1. **明确检查目标**: 具体检查什么问题
2. **给出判断标准**: 什么情况下算违规
3. **区分严重级别**: critical vs warning 的界限
4. **提供上下文依赖**: 需要什么上下文信息辅助判断

---

## 学习规则 (`rules/learned/*.yaml`)

从人工反馈自动生成，有独立的生命周期管理。

```yaml
# 单条学习规则
- id: R-L{NNN}       # 自动递增编号
  name: "规则名称"
  source: human_feedback
  created_from: "feedback/FB-{YYYY}-{NNN}"
  created_at: "{timestamp}"
  severity: warning   # 默认 warning
  pattern_type: structural|semantic|contextual
  check_prompt: |
    从漏报中提取的检查逻辑
  applies_to: [all]
  status: experimental  # 初始状态: experimental|review_pending|active|review_needed|deprecated
  effectiveness:
    times_applied: 0
    times_caught: 0
    false_positive_count: 0
    false_positive_rate: null
```

### pattern_type 说明

| 类型 | 说明 | 示例 |
|------|------|------|
| structural | 结构性模式 | 句式重复、段落结构问题 |
| semantic | 语义性模式 | 语气不符、逻辑矛盾 |
| contextual | 上下文相关 | 与前文设定冲突、状态不一致 |

---

## 动态规则（运行时从知识库加载）

各领域可有独立的知识库，运行时根据内容标签匹配加载。

```
动态规则 = {
  id: "K-{NNN}",
  name: 知识条目名称,
  positive_checks: [应遵循的要点],
  negative_checks: [应避免的问题],
  applies_to: [激活场景标签]
}
```

---

## 规则编号约定

| 前缀 | 范围 | 类型 |
|------|------|------|
| D{NNN} | D001-D999 | 确定性规则 |
| L{NNN} | L001-L999 | LLM 规则 |
| R-L{NNN} | R-L001-R-L999 | 学习规则 |
| K-{NNN} | K-001-K-999 | 知识库动态规则 |

各领域 workspace 可自行扩展编号范围，无需全局协调。
