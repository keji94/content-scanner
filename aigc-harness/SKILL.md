---
name: aigc-harness
description: "AIGC 检测修复闭环协议（通用版）。诊断→沉淀→改写→验证 四阶段自动化闭环，通过 domain-config.yaml 注入领域参数。"
version: "1.0.0"
owner: shared
---

# AIGC Harness 协议

## 概述

AIGC 判定→沉淀→改写→验证 四阶段自动化闭环。当内容被判定为 AI 生成或 AIGC 值高时，自动完成诊断、规则沉淀、定向改写、验证收敛。

**设计原则**：协议通用，领域参数通过 `domain-config.yaml` 的 `aigc_harness` 节注入。

## 触发条件

满足任一：
- 用户报告内容"AI味太重"/"AIGC分数太高"/"降AI味"
- 用户报告外部检测工具的 AIGC 分数
- 上游工作流触发（如内容扫描分数低于阈值）

## 四阶段概览

| Phase | 名称 | 输入 | 输出 |
|-------|------|------|------|
| 1 | 诊断 | 内容路径 + (可选)外部AIGC分数 | full_report + uncovered_patterns |
| 2 | 规则沉淀 | uncovered_patterns | 候选规则 + 替换对 |
| 3 | 定向改写 | report + 新规则 + 原文 | 修订后内容 |
| 4 | 验证 + Fix Loop | 修订内容 + baseline scores | 最终结果 + 规则有效性 |

## 领域配置

所有领域特定参数通过 `domain-config.yaml` → `aigc_harness` 节注入：

```yaml
aigc_harness:
  semantic_dimensions: [...]       # 语义分析维度（领域特定）
  revision_thresholds: {...}       # 修订模式阈值
  convergence: {...}               # 收敛判断阈值
  fix_loop: {...}                  # Fix Loop 参数
  fix_agent: "agent_name"          # 修复执行者
  segment_size: 3000               # 分段处理阈值（字符数）
```

> 完整参数说明 → `reference/harness-workflow.md`

## 依赖

- **content-scanner**：Phase 1 诊断复用 `run_deterministic.py` + 语义分析
- **领域规则包**：`rules/deterministic/`、`rules/llm/`、`rules/replacements/`
- **修复 Agent**：由 `fix_agent` 配置指定

## 详细参考

| 文档 | 路径 |
|------|------|
| 4阶段详细流程 | `reference/harness-workflow.md` |
| 规则沉淀协议 | `reference/precipitation.md` |
