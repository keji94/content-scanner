# 两阶段扫描算法详细规范

## 概述

Content Scanner 采用两阶段检查引擎，以 L2（段落）为扫描单元，L1（句子）为定位单元。所有参数可通过 `context/domain-config.yaml` 覆盖。

---

## Phase 1: 确定性快筛

### 执行条件
- 所有内容检查，始终执行
- 零 LLM 成本

### 流程

```
1. 文本分片
   ├── 按 L1 (句子): 以 l1_separator 分割（默认 。！？）
   └── 按 L2 (段落): 以 l2_separator 分割（默认 \n）

2. 逐句规则扫描
   FOR 每个句子:
     FOR 每条确定性规则:
       ├── regex 类: 正则匹配
       ├── frequency 类: 词频计算 vs 阈值
       ├── structure 类: 段落级统计
       ├── cross_reference 类: 读取上下文源交叉比对
       └── statistics 类: 全文统计计算

3. 收集 deterministic_violations[]
```

### 输出
每条违规记录:
```json
{
  "rule_id": "D{NNN}",
  "rule_name": "规则名称",
  "location": { "paragraph": P, "sentence": S },
  "original_text": "原文片段",
  "severity": "critical|warning|suggestion",
  "weight": N,
  "message": "违规描述"
}
```

---

## Phase 2: 逐段 LLM 深检

### 执行条件
- 所有内容检查，始终执行
- LLM 调用量 = 段落数 × 1（每段一次调用）

### 累积上下文初始化

```
初始上下文 = {
  // 静态上下文（从 context-sources.yaml 声明的文件加载）
  static_context: {
    <领域相关字段>: <从上下文源加载>
  },

  // 动态累积（逐段更新）
  cumulative: {
    key_facts: [],
    state_changes: {},
    information_revealed: [],
    arc_samples: []
  },

  // 滑动窗口
  recent_units: []  // 最多保留 recent_window 个（默认 3）
}
```

### 逐段扫描流程

```
FOR unit_index, unit IN enumerate(content.units):

  // Step 1: 构建当前单元的检查上下文
  IF domain_config.context.pruning.enabled:
    active_rules = determine_active_rules(unit, applicable_rules)
    required_fields = collect_required_fields(active_rules, domain_config.context.pruning.field_rule_map)
    required_fields += domain_config.context.pruning.always_include
    context = build_context(
      static_context.filter(required_fields),
      cumulative.filter(required_fields),
      recent_units
    )
  ELSE:
    context = build_context(
      static_context,      // 从上下文源加载
      cumulative,          // 前 N-1 段的累积结果
      recent_units         // 滑动窗口
    )

  // Step 1.5: 注入 Phase 1 提示（如果启用）
  phase1_hints = []
  focus_areas = []
  IF domain_config.context.enable_phase1_hints:
    phase1_hints = deterministic_violations.filter(v => v.location.paragraph == unit_index)
    IF phase1_hints.length > 0:
      focus_areas = derive_focus_areas(phase1_hints)

  // Step 2: 确定适用的规则
  applicable_rules =
    get_llm_rules()              // rules/llm/ 下的静态规则
    + get_dynamic_rules(tags)     // 知识库/技巧库匹配的动态规则
    + get_learned_rules("active") // rules/learned/ 中 active 的学习规则

  // Step 3: 一次 LLM 调用检查当前单元
  violations = llm_check(unit, context, applicable_rules, phase1_hints, focus_areas)

  // Step 4: 更新累积上下文（含置信度追踪）
  new_facts = extract_key_facts(unit)  // 每条附带 confidence
  FOR fact IN new_facts:
    fact.tentative = fact.confidence < confidence_config.tentative_threshold
    existing = find_contradictory(fact, cumulative.key_facts)
    IF existing AND existing.tentative AND fact.confidence > existing.confidence:
      cumulative.key_facts.replace(existing, fact)  // correction override
    ELSE IF NOT existing:
      cumulative.key_facts.append(fact)
  END

  // state_changes, information_revealed 同理（带置信度）
  update_with_confidence(cumulative.state_changes, extract_state_changes(unit))
  update_with_confidence(cumulative.information_revealed, extract_information(unit))

  IF unit_index % emotional_sample_rate == 0:
    cumulative.arc_samples.append(extract_arc_point(unit))

  recent_units.append(unit)
  IF len(recent_units) > recent_window:
    recent_units.pop(0)

  // Step 5: 收集违规
  llm_violations.extend(violations)
```

### LLM Prompt 结构

每次调用包含六个部分：

1. **System Prompt**: 扫描器角色 + 当前位置（单元索引/总数）
2. **Context**: 累积上下文（关键事实 + 状态变化 + 已知信息 + 最近单元）
3. **Domain Context**: 领域上下文源（角色设定/品牌指南/术语表...）
4. **Phase 1 Hints**: Phase 1 确定性检查的提示（可选，仅当该单元有 Phase 1 违规时）
5. **Content**: 当前待检查单元
6. **Output Format**: JSON 数组格式要求

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

### 上下文增长控制

| 字段 | 默认上限 | 控制策略 |
|------|---------|---------|
| key_facts | 50 条 | 超过后压缩旧条目 | 每条附带 confidence + tentative 标记 |
| state_changes | 无 | 只保留最新状态 | 每项附带 confidence + tentative 标记 |
| information_revealed | 30 条 | FIFO | 每条附带 confidence + tentative 标记 |
| arc_samples | 每 N 段采样 | emotional_sample_rate 控制 |
| recent_units | 3 个 | 滑动窗口 |

### Phase 1 → Phase 2 Focus Area 映射

Phase 1 确定性违规可以为 Phase 2 LLM 检查提供聚焦方向。
领域可在 domain-config.yaml 中覆盖此映射。

| Phase 1 违规类别 | 建议 Phase 2 关注 | 说明 |
|----------------|-----------------|------|
| forbidden_pattern (D001-D003) | L012 流水账检测 | 禁止句式可能伴随流水账 |
| word_frequency (D004-D008) | L014 节奏单调 | 疲劳词密集段落节奏可能单调 |
| settings_gate (D013-D015) | L003 设定冲突 | 设定越级/提前释放需 LLM 交叉验证 |
| structure (D009-D012) | L011 对话失真 | 结构异常段落对话质量需检查 |

---

## 评分计算（含去重）

### 违规去重规则

1. **关联分组**: 同一位置 (paragraph, sentence) 的违规，如果属于相关规则类别，归入同一 `correlation_group`
2. **组内计分**: 每个 correlation_group 只计最高 severity 的违规（`is_primary: true`）
3. **独立计分**: 无 correlation_group 的违规独立计分
4. **跨单元**: 不同段落的同一规则触发分别计分（不变）

### 关联类别映射（可在 domain-config.yaml 覆盖）

| 关联组 | 包含的规则类别 | 说明 |
|--------|-------------|------|
| setting_integrity | settings_gate (D013-D015), consistency (L003-L005) | 设定相关问题的不同维度 |
| character_behavior | forbidden_pattern (D001-D003), consistency (L001, L008, L016) | 角色行为的确定性+语义检查 |
| readability | word_frequency (D004-D008), structure (D009-D012), narrative (L011-L014) | 可读性相关问题的不同指标 |

### 评分公式

```
grouped = group_violations(all_violations, correlation_mapping)
score = 100 - Σ(max(v.weight for v in group))  // 每组只计最高
```

### 违规输出增加字段

每条 violation 增加:
```json
{
  "correlation_group": "setting_integrity|character_behavior|readability|null",
  "is_primary": true  // 组内是否为最高 severity
}
```

等级判定: 由 domain-config.yaml 中的 grade_thresholds 定义

---

## Fix Loop

由 Supervisor 编排，Scanner 只负责检查。

```
Round 1:
  Scanner 检查 → 有违规 → Supervisor 协调修复 Agent

Round 2:
  Scanner 复查 → 仍有违规 → Supervisor 协调修复 Agent
  停滞检测: Round2 分数 - Round1 分数 ≤ stagnation_delta → 提示用户

Round 3 (最后一轮):
  Scanner 复查 → 仍有违规 → 上报用户决策

收敛条件: critical == 0 AND warning ≤ {convergence.warning} AND score ≥ {convergence.score}
```
