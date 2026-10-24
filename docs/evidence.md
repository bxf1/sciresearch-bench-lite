# 关键日志与证据链

以下片段由 `tools/prepare_delivery.py` 从既有日志按注明字段提取，数值不改写；这是字段节选，不冒充完整原始日志。原文件路径与 SHA256 可逐项核对。完整轨迹见 Release 的原始证据包。

## Heat G3 r1：研究结束及可信候选登记

来源：[research-runs/research-6615cd7900ba0750-heat-g3-r1/host-events.jsonl](../research-runs/research-6615cd7900ba0750-heat-g3-r1/host-events.jsonl)。SHA256：`f69d8c507767932d9fd9860c4b48a8ecccc06ce52184e1533cddd44aed3834cf`。

提取规则：`kind=research_stopped|registry_closed; select kind,time,fields`。

```json
[
  {
    "kind": "research_stopped",
    "time": 1792718482.467263,
    "fields": {
      "bridge_errors": [],
      "cleanup_errors": {}
    }
  },
  {
    "kind": "registry_closed",
    "time": 1792718483.745457,
    "fields": {
      "attempt_status": "completed",
      "final_id": "candidate-018",
      "first_id": "candidate-017"
    }
  }
]
```

## Heat G3 r1：独立隐藏重放

来源：[research-runs/research-6615cd7900ba0750/final-replays/research-6615cd7900ba0750-heat-g3-r1-a001/result.json](../research-runs/research-6615cd7900ba0750/final-replays/research-6615cd7900ba0750-heat-g3-r1-a001/result.json)。SHA256：`c26617949e97db3695146bb266dae3b39e871ffbdaed4e2641893c4b756c143b`。

提取规则：`diagnostics.first/final; select checkpoint_id,source_hash,evaluation_status,replay_count,score,reward`。

```json
{
  "first": {
    "checkpoint_id": "candidate-017",
    "source_hash": "3623657fcdff83e64e3e2eca4047738955002cea043f0baecf50a21f06bddf13",
    "evaluation_status": "valid",
    "replay_count": 3,
    "score": 21.394330950607056,
    "reward": 0
  },
  "final": {
    "checkpoint_id": "candidate-018",
    "source_hash": "01e6638167d5ecc896c3c88832dc603fdfd8a6bcf90aa60b3fd8bda08f0d9054",
    "evaluation_status": "valid",
    "replay_count": 3,
    "score": 91.53191716630722,
    "reward": 1
  }
}
```

## Heat G3 r1：candidate-017 公开反馈示例

来源：[research-runs/research-6615cd7900ba0750-heat-g3-r1/registry/evaluations/candidate-017/public_feedback.json](../research-runs/research-6615cd7900ba0750-heat-g3-r1/registry/evaluations/candidate-017/public_feedback.json)。SHA256：`e71c429b45a80cebeb5855f79b3ebe039b01f45eb06fef19690ad541cc2ffc93`。

提取规则：`select artifact_valid,attempt_status,public_check_status,formal_timing,cases[0]; other five cases omitted`。

```json
{
  "artifact_valid": true,
  "attempt_status": "completed",
  "public_check_status": "completed",
  "formal_timing": false,
  "cases": [
    {
      "R": 0.9058499699409166,
      "artifact_valid": true,
      "id": "13a841e7b6de490e68f4",
      "roughness": 2774.7137511800242,
      "status": "ok"
    }
  ]
}
```

## Heat G3 r1：candidate-018 公开反馈示例

来源：[research-runs/research-6615cd7900ba0750-heat-g3-r1/registry/evaluations/candidate-018/public_feedback.json](../research-runs/research-6615cd7900ba0750-heat-g3-r1/registry/evaluations/candidate-018/public_feedback.json)。SHA256：`af899397cbab22dbace8a74d2cf4b953ded898e0b753b05742ae924a59e8c83a`。

提取规则：`select artifact_valid,attempt_status,public_check_status,formal_timing,cases[0]; other five cases omitted`。

```json
{
  "artifact_valid": true,
  "attempt_status": "completed",
  "public_check_status": "completed",
  "formal_timing": false,
  "cases": [
    {
      "R": 0.981504023773167,
      "artifact_valid": true,
      "id": "13a841e7b6de490e68f4",
      "roughness": 44.838834912267004,
      "status": "ok"
    }
  ]
}
```

## 冻结资源验收

来源：[logs/resource-acceptance-local-002/summary.json](../logs/resource-acceptance-local-002/summary.json)。SHA256：`bd333f53d9785f56deb975b7c31aabb98e39e9b97e8d4af18f301b2f777dce2f`。

提取规则：`select listed top-level fields`。

```json
{
  "status": "passed",
  "formal_resources_accepted": true,
  "resources": {
    "filesystem_depth": 32,
    "filesystem_entries": 2000,
    "heat_ode_worker_seconds": 120,
    "judge_seconds": 1200,
    "max_evaluations": 20,
    "output_bytes": 268435456,
    "poisson_worker_seconds": 60,
    "research_memory_bytes": 4294967296,
    "research_seconds": 1800,
    "research_vcpu": 4,
    "source_bytes": 20971520,
    "source_files": 1000,
    "tmp_bytes": 67108864,
    "worker_memory_bytes": 4294967296,
    "worker_pids": 128,
    "worker_swap_bytes": 0,
    "worker_threads": 1,
    "worker_vcpu": 1
  },
  "model_calls": 0,
  "final_test_scores_accessed": false
}
```

## Poisson G2：无效计时原始判定

来源：[logs/formal-execution-local-004/window-final-poisson-research-6615cd7900ba0750-poisson-g2-r1/acceptance.json](../logs/formal-execution-local-004/window-final-poisson-research-6615cd7900ba0750-poisson-g2-r1/acceptance.json)。SHA256：`ea46a27ae666f2afb8b377d30b3f947d845d880d846182362e721791bae72051`。

提取规则：`select listed top-level fields`。

```json
{
  "status": "rejected",
  "evaluation_status": "invalid",
  "violations": [
    {
      "active": [
        {
          "command": "/Applications/iKuuuVPN.app/Contents/MacOS/iKuuuVPNCore",
          "core_percent": 6.4058037859730605,
          "pid": "57101"
        }
      ],
      "issues": [
        "unrelated_active_process"
      ],
      "swap": {
        "Swapins": 0,
        "Swapouts": 0
      },
      "unix": 1792743603.8685079
    }
  ],
  "observer_errors": []
}
```

## 全部正式研究与评分审计

来源：[logs/formal-execution-local-004/final-audit-001.json](../logs/formal-execution-local-004/final-audit-001.json)。SHA256：`788b9746808aa9842e4f3d81053aff25fdc29f15120a3961cf36f3fbb31b5cde`。

提取规则：`select listed top-level fields`。

```json
{
  "status": "execution_closed_with_one_invalid_performance_measurement",
  "valid_research_sessions": 15,
  "valid_final_scientific_results": 14,
  "with_first_final": 9,
  "no_valid_submission": 6,
  "physical_worker_batches": 93,
  "physical_worker_case_executions": 1116,
  "unattempted_operations": []
}
```

## 冻结版本测试日志

[原日志](../logs/formal-freeze-local-003/unit-tests-final.txt)，SHA256：`60e6cb7a1c506189ef50d296325b53e70b5297534158b4d834f77753656a86f7`。以下为原日志末行；不是本次整理重新运行的测试。

```text
357 passed, 2 warnings in 14.07s
```

## 失败与未提交的追溯

原正式批次的 [提交与重复调用诊断](submission-diagnosis-2026-10-23.md)覆盖接口导出失败、逐字循环、仅递增文件名和不同种子模拟；[取消补跑诊断](supplemental-results-2026-10-24.md)另列提前终止的会话，不进入正式分母。完整数据索引见 [data/README](../data/README.md)。
