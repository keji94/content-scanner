# 两阶段扫描算法详细规范

## 概述

Content Scanner 采用两阶段检查引擎，以 L2（段落）为扫描单元，L1（句子）为定位单元。所有参数可通过 `context/domain-config.yaml` 覆盖。

v2 架构：确定性计算由 Python 脚本执行，Agent 只负责 Phase 2 LLM 调用。

---

## Phase 1: 确定性快筛

### 执行条件
- 所有内容检查，始终执行
- 零 LLM 成本

### CLI 调用

```bash
# Step 1: 文本分片
python3 scripts/split_text.py \
  --input <文本文件路径> \
  --config <domain-config.yaml路径>
# 输出: { l1_units[], l2_units[], l2_to_l1, metadata }

# Step 2: 确定性规则检查
python3 scripts/run_deterministic.py \
  --input <文本文件路径> \
  --rules-dir <确定性规则目录> \
  --config <domain-config.yaml路径> \
  --context-dir <上下文目录> \
  --genre <题材>
# 输出: { violations[], summary }
```

### 支持的规则类型

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

### 违规输出格式

每条违规记录:
```json
{
  "rule_id": "D{NNN}",
  "rule_name": "规则名称",
  "location": { "paragraph": P, "sentence": S },
  "original_text": "原文片段",
  "severity": "critical|warning|suggestion",
  "weight": N,
  "issue": "违规描述",
  "source": "deterministic",
  "correlation_group": null,
  "is_primary": true
}
```

---

## Phase 2: 逐段 LLM 深检

### 执行条件
- 所有内容检查，始终执行
- LLM 调用量 = 段落数 × 1（每段一次调用）

### 逐段循环

```
1. 初始化累积上下文
   exec update_context.py --init \
     --context-json /tmp/context.json \
     --extractions /dev/null \
     --config <domain-config.yaml> \
     --context-sources <context-sources.yaml> \
     --unit-index 0

2. FOR 每个段落 (unit_index):

   a. 组装检查 prompt
      exec prepare_phase2_unit.py \
        --split-json /tmp/split.json \
        --context-json /tmp/context.json \
        --phase1-violations /tmp/phase1_violations.json \
        --config <domain-config.yaml> \
        --unit-index <N>
      → 输出 { system_prompt, context, domain_context, phase1_hints, content, output_format }

   b. Agent 做 LLM 语义判断（一次调用检查当前段落）
      - 加载 rules/llm/ 下的 LLM 规则 + rules/learned/ 中 active 的学习规则
      - 使用 prepare_phase2_unit.py 输出的 prompt 结构

   c. Agent 写 extractions.json:
      {
        "key_facts": [{"fact": "...", "confidence": 0.9}],
        "character_states": {"角色A": {"value": "受伤", "confidence": 0.85}},
        "information_revealed": [{"info": "...", "confidence": 0.7}]
      }

   d. 更新累积上下文
      exec update_context.py \
        --context-json /tmp/context.json \
        --extractions /tmp/extractions.json \
        --config <domain-config.yaml> \
        --context-sources <context-sources.yaml> \
        --unit-index <N> --unit-text "段落原文..."

   e. 收集 LLM 违规 → llm_violations[]
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
| key_facts | 50 条 | 超过后压缩旧条目，每条附带 confidence + tentative 标记 |
| state_changes | 无 | 只保留最新状态，每项附带 confidence + tentative 标记 |
| information_revealed | 30 条 | FIFO，每条附带 confidence + tentative 标记 |
| arc_samples | 每 N 段采样 | emotional_sample_rate 控制 |
| recent_units | 3 个 | 滑动窗口 |

### Phase 1 → Phase 2 Focus Area 映射

Phase 1 确定性违规可以为 Phase 2 LLM 检查提供聚焦方向。

| Phase 1 违规类别 | 建议 Phase 2 关注 | 说明 |
|----------------|-----------------|------|
| forbidden_pattern (D001-D003) | L012 流水账检测 | 禁止句式可能伴随流水账 |
| word_frequency (D004-D008) | L014 节奏单调 | 疲劳词密集段落节奏可能单调 |
| settings_gate (D013-D015) | L003 设定冲突 | 设定越级/提前释放需 LLM 交叉验证 |
| structure (D009-D012) | L011 对话失真 | 结构异常段落对话质量需检查 |

---

## 评分计算（含去重）

### CLI 调用

```bash
python3 scripts/calculate_score.py \
  --violations /tmp/all_violations.json \
  --config <domain-config.yaml路径>
# 输出: { score, grade, deduction, critical_count, warning_count, suggestion_count, total_violations }
```

### 违规去重规则

1. **关联分组**: 同一位置 (paragraph, sentence) 的违规，如果属于相关规则类别，归入同一 `correlation_group`
2. **组内计分**: 每个 correlation_group 只计最高 severity 的违规（`is_primary: true`）
3. **独立计分**: 无 correlation_group 的违规独立计分
4. **跨单元**: 不同段落的同一规则触发分别计分

### 评分公式

```
score = 100 - Σ(weight of primary violations)
```

等级判定由 `domain-config.yaml` → `scoring.grade_thresholds` 定义（A/B/C/D）。

---

## Fix Loop

由 Supervisor 编排，Scanner 只负责检查。

```
Round 1: Scanner 检查 → 有违规 → Supervisor 协调修复 Agent
Round 2: Scanner 复查 → 仍有违规 → Supervisor 协调修复 Agent
         停滞检测: Round2 分数 - Round1 分数 ≤ stagnation_delta → 提示用户
Round 3: Scanner 复查 → 仍有违规 → 上报用户决策

收敛条件: critical == 0 AND warning ≤ {convergence.warning} AND score ≥ {convergence.score}
```

---

## 完整检查报告格式

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
