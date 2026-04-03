# AIGC Harness 4阶段详细流程

## domain-config.yaml 参数

```yaml
aigc_harness:
  # 语义分析维度（领域特定）
  semantic_dimensions:
    - {name: "维度名", weight: N}
    # ... 各领域自定义

  # 修订模式阈值（ai_trace_score 分界线）
  revision_thresholds:
    rewrite: 60        # < 此值 → rewrite
    anti_detect: 70    # rewrite~此值 → anti-detect
    polish: 80         # anti_detect~此值 → polish

  # 收敛判断
  convergence:
    pass_score: 75                 # post_score >= 此值即 PASS
    significant_improvement: 10    # delta >= 此值 → 显著改善
    acceptable_improvement: 5      # delta >= 此值 → 可接受

  # Fix Loop
  fix_loop:
    max_rounds: 2                  # 最大追加轮次
    stagnation_delta: 2            # delta <= 此值 → 停滞

  # 修复执行者
  fix_agent: "agent_name"          # 领域特定 Agent 名称

  # 分段处理阈值（字符数）
  segment_size: 3000
```

---

## Phase 1: 诊断

```
输入: 内容路径 + (可选)段范围 + (可选)外部AIGC分数
```

### 1.1 门控检测

```
调用检测模块({mode:"quick", content_path}) → gate_report

IF gate_report.score >= revision_thresholds.polish:
  提示用户"AI痕迹较低({score}分)，是否继续优化？"
  用户确认 → 继续 | 用户取消 → 结束
```

### 1.2 增强检测

```
调用检测模块({mode:"enhanced", content_path, include_semantic:true})
  → full_report

full_report 含:
- ai_trace_score (0-100)
- 确定性违规 per-segment (来自 rules/deterministic/)
- 语义分析 per-segment（按 domain-config 的 semantic_dimensions）
- 统计特征（TTR/句长std/段长std/主动句比例）
- segment_violation_map: {段序号: [违规列表]}
```

### 1.3 规则覆盖分析

Supervisor 本地执行：

```
1. 读取 rules/_index.md（轻量索引）
2. 对照 full_report.violations → 每个违规映射到规则 ID
3. 标记: covered（有规则覆盖）vs uncovered（无规则覆盖）
4. 对 uncovered 的语义分析发现，检查 ai-traces.yaml 替换表覆盖
5. 输出: uncovered_patterns 列表

IF uncovered_patterns 为空 → 跳过 Phase 2，直进 Phase 3
```

---

## Phase 2: 规则沉淀

> 详细协议见 `reference/precipitation.md`

```
输入: Phase 1 full_report + uncovered_patterns
前提: IF uncovered_patterns 为空 → 跳过，直进 Phase 3
```

### 2.1 模式分类

```
对每个 uncovered_pattern 判断类型:
├── 确定性模式（可用正则/统计） → 候选 D 规则
├── 替换对（AI套话→人类表达）  → 候选替换条目
└── 语义模式（需LLM判断）      → 候选 L 规则
```

### 2.2 生成候选规则

- 确定性/语义 → `rules/learned/harnessed_H{NNN}.yaml`（status: experimental）
- 替换对 → 追加到 `rules/replacements/ai-traces.yaml`

### 2.3 更新索引

- 更新 `rules/learned/_index.yaml`
- 更新 `rules/_index.md` changelog

---

## Phase 3: 定向改写

```
输入: Phase 1 report + Phase 2 新规则（如有） + 原文
```

### 3.1 修订模式选择

```
基于 ai_trace_score:
├── < revision_thresholds.rewrite      → rewrite（保留 30-50%）
├── rewrite ~ anti_detect              → anti-detect（保留 40-60%）
└── anti_detect ~ polish               → polish + 定点 anti-detect（保留 70%+）

基于 segment_violation_map:
├── 全文低分     → 全文处理
├── 局部段落低分 → 仅处理高违规 segment
└── 混合         → 高违规段 rewrite，其余 polish
```

### 3.2 分段处理（内容 > segment_size 时）

```
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
```

### 3.3 短内容直接处理（内容 ≤ segment_size）

```
调用修复 Agent({
  mode, violations: full_report.violations,
  new_rules: Phase 2 新规则
}) → revised_content
```

---

## Phase 4: 验证 + Fix Loop

```
输入: 修订后内容 + Phase 1 baseline scores
```

### 4.1 复检

```
调用检测模块({mode:"enhanced", content_path})
  → post_report
```

### 4.2 分数对比 + 收敛判断

```
delta = post_report.ai_trace_score - phase1_report.ai_trace_score

├── post >= pass_score AND delta >= significant_improvement → PASS（显著改善）
├── post >= pass_score AND delta >= acceptable_improvement  → PASS（可接受）
├── delta < 0                  → REGRESSION（退化，回滚原文）
└── 其他                        → 进入 Fix Loop
```

### 4.3 Fix Loop

```
round = 1
WHILE round <= max_rounds AND post_score < pass_score:
  a. 调用修复 Agent({mode:"spot-fix", violations: 残留违规})
  b. 调用检测模块({mode:"quick"}) → recheck
  c. 停滞检测: delta <= stagnation_delta → 展示趋势，等用户决策
  d. 退化检测: delta < 0 → 回滚原文，上报用户
  e. round += 1
```

### 4.4 规则有效性更新

```
FOR each Phase 2 新增规则:
  检查 post_report 是否仍触发该规则
  → 更新 rules/learned/ 中 effectiveness 指标
```

### 4.5 内容完整性检查（可选）

```
IF 修订模式 = rewrite OR delta > 20:
  执行完整性检查 → 确保: 无新 critical、无关键信息丢失
```

### 4.6 返回结果

```
- AI 痕迹分数: {before} → {after}
- 修改段落数
- 新沉淀规则数
- 规则覆盖分析
```

---

## 上下文窗口策略

### 渐进式加载

```
Tier 0 - 始终加载:
  rules/_index.md

Tier 1 - Phase 1 按需:
  rules/deterministic/xxx.yaml    # 仅加载有违规的文件
  rules/replacements/ai-traces.yaml

Tier 2 - Phase 2 按需:
  rules/learned/_index.yaml
  rules/learned/H*.yaml

Tier 3 - Phase 3 每个 segment（~1500 token）:
  segment原文(~600) + 违规(~200) + 替换表(~150) + 相邻上下文(~400)
```

### Supervisor 常驻上下文

全流程 Supervisor 上下文约 **500 token**：用户消息 + Phase 1 摘要 + Phase 2 规则摘要 + 分数历史。

分段处理时每个修复 Agent spawn 独立上下文，不累积。
