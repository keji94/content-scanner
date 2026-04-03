# AIGC Harness 沉淀协议：从分析到候选规则

## 概述

Phase 1 诊断完成后，对 uncovered_patterns（无现有规则覆盖的 AI 痕迹模式）执行分类→生成→索引更新。

## 模式分类

对每个 uncovered_pattern，根据特征判断规则类型：

| 特征 | 判定类型 | 目标位置 |
|------|---------|---------|
| 可用正则/pattern匹配 | 确定性模式 | `rules/learned/harnessed_H{NNN}.yaml` |
| 可量化阈值（密度、频次） | 确定性模式 | `rules/learned/harnessed_H{NNN}.yaml` |
| AI套话→人类表达映射 | 替换对 | `rules/replacements/ai-traces.yaml` |
| 需语义/上下文判断 | 语义模式 | `rules/learned/harnessed_H{NNN}.yaml` |

## 候选规则生成

### 确定性模式模板

```yaml
id: H{NNN}  # 从 rules/learned/_index.yaml 读取当前最大值+1
name: "从AIGC Harness提取: {模式简述}"
source: aigc_harness
created_at: "{ISO8601}"
severity: warning  # 默认 warning，除非模式特别严重
status: experimental

# 确定性规则选择以下 type 之一:
type: pattern          # 单个正则
# type: patterns       # 多个正则（任一匹配即触发）
# type: density        # 词密度检查
# type: pattern_list   # 正则列表

pattern: '{正则表达式}'
# 或 patterns: ['{正则1}', '{正则2}']
# 或 words: ['{词1}', '{词2}']  # density 类型
# threshold: "每{N}字允许{M}次"

message: "{违反描述}，{修改建议}"
applies_to: [all]
note: "AIGC Harness auto-generated"

# 有效性追踪（自学习生命周期使用）
effectiveness:
  times_applied: 0
  times_caught: 0
  false_positive_count: 0
```

### 语义模式模板

```yaml
id: H{NNN}
name: "从AIGC Harness提取: {模式简述}"
source: aigc_harness
created_at: "{ISO8601}"
severity: warning
status: experimental
pattern_type: semantic

check_prompt: |
  检查以下文本是否存在{模式描述}:
  - 判断标准: {具体标准}
  - 示例: "{正面示例}" vs "{反面示例}"
  - 注意: {边界条件/排除情况}

applies_to: [all]
note: "AIGC Harness auto-generated, requires LLM judgment"

effectiveness:
  times_applied: 0
  times_caught: 0
  false_positive_count: 0
```

### 替换对追加格式

追加到 `rules/replacements/ai-traces.yaml`：

```yaml
  - ai_pattern: "{AI套话/句式}"
    human_alternatives: ["{替换1}", "{替换2}"]
    severity: warning
    source: aigc_harness
    note: "AIGC Harness 提取"
```

## 索引更新流程

### 1. 更新 rules/learned/_index.yaml

```yaml
# 追加到对应列表
experimental_rules:
  - H{NNN}  # 新增规则ID

# 递增总数
total_learned_rules: {原值+1}
```

### 2. 更新 rules/_index.md

```markdown
## Changelog
- {日期}: AIGC Harness 沉淀 {N} 条规则: H{NNN}({模式名}), ...
- {日期}: 替换表追加 {M} 条（来源: AIGC Harness）
```

## 生命周期管理

Harness 生成的规则遵循现有自学习生命周期：

```
experimental → (应用≥10次, 有效率≥50%) → review_pending → (人工审核) → active
```

- Phase 4 验证时自动更新 `times_applied` 和 `times_caught`
- 规则在 `experimental` 状态参与检查，但仅记录不影响正式评分
- 人工批量审核可在后续会话中进行

## 上下文预算

沉淀阶段 Supervisor 上下文：

```
rules/learned/_index.yaml    ~100 token  # 读取当前规则列表
uncovered_patterns 列表      ~100 token  # Phase 1 输出
生成 1-3 条候选规则          ~300 token  # 写入
───────────────────────────────────────
合计                         ~500 token
```

每次只处理一个 uncovered_pattern，生成后立即写入文件，不在上下文中累积。
