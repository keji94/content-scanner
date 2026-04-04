# 脚本 API 参考（v2）

> **注意**: 本文件在 v1 中定义了 9 个领域无关工具。v2 已将所有工具替换为 CLI 脚本。
> 详细的 CLI 用法请参考 `reference/scan-algorithm.md`。

## v1 工具 → v2 脚本映射

| v1 工具 | v2 脚本 | 说明 |
|---------|---------|------|
| `split_text` | `scripts/split_text.py` | CLI 参数不变 |
| `run_deterministic_rules` | `scripts/run_deterministic.py` | Phase 1 全部确定性规则 |
| `calculate_statistics` | (已合并) | 统计计算由 `run_deterministic.py` 内部处理 |
| `run_llm_check_per_unit` | Agent 负责 + `scripts/prepare_phase2_unit.py` | LLM 调用由 Agent 执行，prompt 组装由脚本辅助 |
| `update_context` | `scripts/update_context.py` | CLI 参数不变 |
| `calculate_check_score` | `scripts/calculate_score.py` | CLI 参数不变 |
| `generate_check_report` | `scripts/generate_report.py` | CLI 参数不变 |
| `process_human_feedback` | `reference/self-learning.md` | Agent 根据 protocol 处理反馈 |
| `generate_candidate_rule` | `reference/self-learning.md` | Agent 根据 protocol 生成候选规则 |

## 变更要点

- v1 的工具定义模式（input/output schema）已被 CLI 参数 + JSON stdout 取代
- 所有脚本支持 `--config` 读取 `domain-config.yaml`
- 统计计算（TTR、句长 std 等）不再作为独立工具，由 `run_deterministic.py` 的 `statistical` 类型规则内部处理
- Phase 2 的 LLM 调用始终由 Agent 执行，脚本只负责数据组装（`prepare_phase2_unit.py`）和上下文更新（`update_context.py`）
