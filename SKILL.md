---
name: content-scanner
description: "通用内容扫描协议 v2。确定性规则由 Python 脚本执行，Agent 只负责 Phase 2 语义判断和工具调用编排。"
version: "2.0.0"
owner: shared
---

# Content Scanner 共享协议 v2

## 概述

通用内容扫描框架，"共享协议 + 领域规则包" 实现跨场景复用。

**脚本负责**：文本分割、确定性规则、上下文簿记、评分计算、报告格式化
**Agent 负责**：Phase 2 语义判断、上下文提取、自学习决策

---

## 架构

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

## Agent Map

| Step | Agent Action | Script | Output |
|------|-------------|--------|--------|
| 1 | 文本分片 | `split_text.py --input --config` | `{l1_units, l2_units, metadata}` |
| 2 | Phase 1 确定性检查 | `run_deterministic.py --input --rules-dir --config --genre` | `{violations[], summary}` |
| 3 | Phase 2 逐段 LLM 深检 | Agent LLM 判断 + `prepare_phase2_unit.py` + `update_context.py` | `llm_violations[]` |
| 4 | 合并违规 + 评分 | `calculate_score.py --violations --config` | `{score, grade, deduction}` |
| 5 | 生成报告 | `generate_report.py --violations --score --split --config` | 完整报告 JSON |

详细 CLI 命令、Phase 2 循环流程、LLM prompt 结构 → `reference/scan-algorithm.md`

---

## 领域注入点

各 workspace 必须提供以下文件：

| 注入点 | 文件位置 | 必需 |
|--------|---------|------|
| 确定性规则 | `rules/deterministic/*.yaml` | 是 |
| LLM 规则 | `rules/llm/*.yaml` | 是 |
| 规则索引 | `rules/_index.yaml` | 是 |
| 上下文源声明 | `context/context-sources.yaml` | 是 |
| 领域配置 | `context/domain-config.yaml` | 是（有默认值） |
| 修复 Agent | `context/domain-config.yaml` → fix_agent | 是 |
| 学习规则 | `rules/learned/*.yaml` | 否 |

可运行示例 → `examples/chinese-novel/`

---

## 脚本目录

| 脚本 | 用途 |
|------|------|
| `scripts/split_text.py` | L1/L2 文本分片 |
| `scripts/run_deterministic.py` | Phase 1 全部确定性规则 |
| `scripts/prepare_phase2_unit.py` | Phase 2 单元 prompt 组装 |
| `scripts/update_context.py` | 累积上下文更新 |
| `scripts/calculate_score.py` | 评分 + 关联分组去重 |
| `scripts/generate_report.py` | 报告 JSON 组装 |

依赖：`pyyaml`, `jieba`

---

## Fix Loop

由 Supervisor 编排，Scanner 只负责检查。最多 `{max_rounds}` 轮，收敛条件：`critical == 0 AND warning ≤ {convergence.warning} AND score ≥ {convergence.score}`。停滞检测：`delta ≤ {stagnation_delta}` → 提示用户。

---

## 关键参考

| 文档 | 路径 |
|------|------|
| 扫描算法详规（CLI 工作流 + Phase 2 prompt） | `reference/scan-algorithm.md` |
| 规则格式规范（11 种 type + LLM/学习规则 schema） | `reference/rule-schema.md` |
| 上下文结构 + domain-config 完整 schema | `reference/context-schema.md` |
| 自学习机制（反馈处理 + 规则生命周期） | `reference/self-learning.md` |
| 脚本 API（v1 工具 → v2 脚本映射） | `reference/tools-common.md` |
