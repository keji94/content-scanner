# 累积上下文结构规范

## 概述

Content Scanner 维护一个逐段递进的累积上下文，确保检查第 N 段时拥有前 N-1 段的关键信息。上下文结构由领域配置参数化。

---

## 上下文结构

### 完整结构

```
累积上下文 = {
  // === 静态上下文（从上下文源加载，全程不变）===
  static_context: {
    <字段由 context-sources.yaml 声明>
    // 例如网文: chapter_summary, truth_snapshot
    // 例如自媒体: brand_guidelines, target_audience
  },

  // === 动态累积（逐段更新，含置信度追踪）===
  cumulative: {
    key_facts: [
      { fact: "...", confidence: 0.85, tentative: false, source_paragraph: N }
    ],
    state_changes: {
      "key": { value: "...", confidence: 0.9, tentative: false, updated_at: P }
    },
    information_revealed: [
      { info: "...", confidence: 0.7, tentative: false }
    ],
    arc_samples: []          // 情感/语气曲线采样（不需要置信度）
  },

  // === 滑动窗口 ===
  recent_units: []           // 最近 N 个单元的原文
}
```

### 领域相关部分

| 领域 | static_context 字段 | cumulative 字段 |
|------|---------------------|-----------------|
| 网文 | chapter_summary, truth_snapshot(characters, foreshadowing, settings_release, timeline) | key_facts, character_states, information_revealed, emotional_arc |
| 自媒体 | brand_guidelines, target_audience, editorial_policy | argument_chain, tone_tracker, claim_evidence_map, audience_engagement_points |
| 技术文档 | spec_references, version_map, terminology | concept_definitions, code_refs, version_changes |

---

## context-sources.yaml 格式

各 workspace 的 `context/context-sources.yaml` 声明需要加载的上下文文件：

```yaml
# 上下文源声明
sources:
  - id: source_id           # 唯一标识
    path: "文件路径"         # 相对于项目根目录
    load: always|on_demand   # 加载策略
    max_tokens: N            # 最大 token 限制
    description: "用途说明"

# 上下文字段映射（领域相关）
context_mapping:
  # 静态上下文字段 → 来源映射
  static_fields:
    field_name:
      source: source_id
      extract: "提取逻辑（可选）"

  # 动态累积字段定义
  cumulative_fields:
    - name: field_name
      type: list|dict|scalar
      max_size: N            # 增长上限
      update_strategy: append|merge|replace|correction
      sample_rate: N         # 采样频率（0=每段，N=每N段）
      # 置信度追踪（可选）
      confidence:
        track: true|false           # 是否追踪置信度
        tentative_threshold: 0.7    # 低于此值标记为 tentative
        correction_strategy: override  # override: 高置信度覆盖低置信度
```

---

## domain-config.yaml 格式

各 workspace 的 `context/domain-config.yaml` 定义可覆盖的参数：

```yaml
# 领域配置
domain_config:
  # 文本分片参数
  text_units:
    l1_separator: "。！？"          # 句子分隔符
    l2_separator: "\\n"             # 段落分隔符
    scan_unit: "l2"                 # 扫描粒度: l2(段落) 或 l3(场景块)
    locate_unit: "l1"               # 定位粒度

  # 上下文参数
  context:
    recent_window: 3                # 滑动窗口大小
    max_key_facts: 50               # 关键事实上限
    max_information: 30             # 已揭示信息上限
    emotional_sample_rate: 3        # 情感采样频率（每N段）
    enable_phase1_hints: true       # 是否在 Phase 2 注入 Phase 1 提示

  # 评分参数
  scoring:
    critical_weight: 10
    warning_weight: 3
    suggestion_weight: 1
    grade_thresholds:
      A: { min_score: 90, max_critical: 0, max_warning: 3 }
      B: { min_score: 80, max_critical: 0, max_warning: 5 }
      C: { min_score: 70, max_critical: 2 }
      D: { min_score: 0, max_critical: 999 }
    # 关联分组映射（用于评分去重，同位置同组只计最高 severity）
    correlation_groups:
      setting_integrity: []    # 例: [D013, D014, D015, L003, L004, L005]
      character_behavior: []   # 例: [D001, D002, D003, L001, L008, L016]
      readability: []          # 例: [D004, D005, D006, D007, D008, D009, D010, D011, D012, L011, L012, L013, L014]

  # Fix Loop 参数
  fix_loop:
    max_rounds: 3
    convergence:
      critical: 0
      warning: 3
      score: 85
    stagnation_delta: 2

  # 自学习参数
  self_learning:
    upgrade_threshold:
      times_applied: 10
      effectiveness: 0.5
    downgrade_threshold:
      false_positive_rate: 0.3
      times_applied: 5
    # review_pending 队列配置
    review_pending:
      auto_approve_after: null  # 可选: N 天后自动批准（null = 需人工）
      max_pending: 20           # review_pending 队列上限

  # 修复 Agent
  fix_agent: "reviser"              # 修复动作由谁执行
```

### 参数说明

| 参数组 | 关键参数 | 说明 |
|--------|---------|------|
| text_units | l1_separator | 句子级别分割符，影响 Phase 1 粒度 |
| text_units | scan_unit | 扫描粒度，l2=逐段，l3=逐场景块 |
| context | recent_window | 滑动窗口大小，影响 LLM prompt 长度 |
| context | max_key_facts | 关键事实 FIFO 上限，控制上下文膨胀 |
| scoring | grade_thresholds | ABCD 等级判定条件，完全可定制 |
| fix_loop | convergence | 收敛条件，决定 Fix Loop 何时停止 |
| fix_loop | stagnation_delta | 停滞检测阈值，分数变化过小视为停滞 |
| self_learning | upgrade/downgrade | 规则生命周期升降级条件 |

---

## 上下文增长控制策略

| 字段类型 | 控制策略 | 默认参数 |
|---------|---------|---------|
| 列表型 (key_facts, information_revealed) | FIFO + 压缩 | max_size 上限，超出压缩旧条目 |
| 字典型 (state_changes) | Merge | 只保留最新值 |
| 采样型 (arc_samples) | 等间隔采样 | sample_rate 控制频率 |
| 窗口型 (recent_units) | 滑动窗口 | recent_window 控制大小 |
| 置信度控制 | tentative 标记 | confidence < tentative_threshold 的条目标记为 tentative |

---

## 置信度与纠错机制

### 工作原理

1. Phase 2 每段检查完后，LLM 提取结果附带 confidence score (0.0-1.0)
2. confidence < tentative_threshold 的提取标记为 `tentative`
3. 后续段落提取到矛盾信息时:
   - 新提取的 confidence > 原 tentative 条目的 confidence → 覆盖原条目 (correction_strategy: override)
   - 新提取的 confidence <= 原条目的 confidence → 保留原条目，新条目不入库
4. 非矛盾信息正常追加

### 矛盾检测规则

两个提取视为矛盾的条件（领域相关，可覆盖）:
- 同一实体(角色/地点/设定)的状态描述不同
- 同一事件的描述存在互斥细节
- 数值型事实(距离/时间/数量)不一致

### 配置示例

```yaml
cumulative_fields:
  - name: key_facts
    confidence:
      track: true
      tentative_threshold: 0.7
      correction_strategy: override
  - name: character_states
    confidence:
      track: true
      tentative_threshold: 0.6   # 角色状态较难判断，阈值略低
      correction_strategy: override
```

---

## 自适应上下文裁剪

默认行为: 加载所有上下文字段传入每次 LLM 调用。

开启条件: `domain-config.yaml` 中 `context.pruning.enabled = true`

### 工作原理

1. 定义上下文字段 → 规则的依赖映射 (`field_rule_map`)
2. 扫描单元时，根据段落内容类型确定 active 规则集
3. 合并所有 active 规则依赖的上下文字段
4. 仅加载声明的上下文字段 + `always_include` 中的字段

### 配置格式

在 `domain-config.yaml` 的 `context` 节下添加:

```yaml
  context:
    # ... 现有字段 ...
    pruning:
      enabled: false              # 默认关闭
      # 上下文字段 → 规则的依赖映射
      field_rule_map:
        # 格式: 上下文字段名: [依赖此字段的规则ID列表]
        # 例: characters: [L001, L004, L008, L016]
      # 始终加载的字段（不受裁剪影响）
      always_include:
        - recent_units
```

### 估算节省

| 段落类型 | 可能加载的字段子集 | 估算节省 |
|---------|-----------------|---------|
| 纯对话 | characters, character_states, foreshadowing | 40-50% |
| 动作/战斗 | characters, character_states, timeline, key_facts | 40-50% |
| 描写/设定 | settings_release, timeline, key_facts | 50-60% |
| 混合段落 | 全部加载 | 0% |
