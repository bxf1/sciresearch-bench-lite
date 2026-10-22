"""Export trusted calibration records and stage evidence, without running solvers.

Only author-calibration scores are read. Existing logs and original JSON results
are never modified. CSV null is the literal `null`, including unknown costs.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
from pathlib import Path

from .common import file_hash, read_json, write_json

METHOD_LABELS = {
    ("heat", "ls"): "32模态未正则化 LS", ("heat", "rank5"): "前5模态 LS",
    ("heat", "tikhonov"): "固定 Tikhonov α=1e-5", ("heat", "discrepancy"): "discrepancy Tikhonov",
    ("heat", "tsvd"): "TSVD", ("ode", "raw"): "原始差分+稠密 LS",
    ("ode", "fixed"): "固定 SG31/STLSQ.02", ("ode", "search"): "SG/STLSQ 公开验证选参",
    ("poisson", "cg"): "无预条件 CG", ("poisson", "jacobi"): "Jacobi-CG", ("poisson", "lu"): "LU复用4 RHS",
}


def _cell(value):
    if value is None:
        return "null"
    if isinstance(value, (dict, list, tuple, bool)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return value


def _csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: _cell(row.get(key)) for key in fields} for row in rows)


def generation_evidence(project, data):
    generation = read_json(data / "private/generation.json")
    rows = []
    tasks = {}
    for path in sorted((data / "private").glob("*/*/cases/*/manifest.json")):
        case = read_json(path)
        task, split, level, index = case["namespace"]
        rows.append({"task": task, "split": split, "level": level,
                     "qc_passed": case["evidence"]["qc"]["passed"]})
    for task in ("heat", "ode", "poisson"):
        audit = read_json(data / "private" / task / "split_audit.json")
        tasks[task] = {
            "cases": sum(row["task"] == task for row in rows),
            "qc_passed": sum(row["task"] == task and row["qc_passed"] for row in rows),
            "splits": {split: sum(row["task"] == task and row["split"] == split for row in rows)
                       for split in ("public-dev", "author-calibration", "final-test")},
            "latent_unique": audit["latent_unique"], "operator_unique": audit.get("operator_unique"),
        }
    reproduction_path = project / "freezes/data-reproduction-local.json"
    reproduction = read_json(reproduction_path) if reproduction_path.exists() else None
    return {"dataset": data.name, "status": generation["status"], "case_count": len(rows),
            "qc_passed": sum(row["qc_passed"] for row in rows), "tasks": tasks,
            "versions": {key: generation.get(key) for key in ("version", "python", "numpy", "scipy", "platform", "bit_generator")},
            "same_entropy_reproduction": reproduction,
            "generation_manifest_sha256": file_hash(data / "private/generation.json")}


def model_evidence(project):
    records = []
    for path in sorted((project / "logs").glob("model-smoke-*/result.json")):
        source = read_json(path)
        fields = ("attempt_status", "parent_attempt", "study_phase", "formal", "model_requested", "model_wall_seconds",
                  "cost_usd", "network_status", "resource_status", "research_container_removed")
        records.append({"run_id": path.parent.name, "evidence": path.relative_to(project).as_posix(),
                        "evidence_sha256": file_hash(path), **{key: source.get(key) for key in fields},
                        "input_tokens": (source.get("model_usage") or {}).get("n_input_tokens"),
                        "cached_tokens": (source.get("model_usage") or {}).get("n_cache_tokens"),
                        "output_tokens": (source.get("model_usage") or {}).get("n_output_tokens"),
                        "source_hash": (source.get("source") or {}).get("source_hash")})
    return records


def engineering_evidence(project):
    records = {"research_network": [], "file_bridge": []}
    for key, pattern in (("research_network", "research-network-probe-*/result.json"),
                         ("file_bridge", "file-bridge-runtime-*/result.json")):
        for path in sorted((project / "logs").glob(pattern)):
            value = read_json(path)
            rows = value.get("probes", [])
            records[key].append({"run_id": path.parent.name, "evidence": path.relative_to(project).as_posix(),
                                 "evidence_sha256": file_hash(path), "status": value.get("status"),
                                 "formal": value.get("formal"), "model_calls": value.get("model_calls"),
                                 "controller_sha256": value.get("controller_sha256"),
                                 "passed": sum(row.get("passed") is True for row in rows) if rows else None,
                                 "total": len(rows) if rows else None,
                                 "hardening_verified": value.get("requested_hardening_verified"),
                                 "forbidden_http_requests_rejected": value.get("forbidden_http_requests_rejected"),
                                 "own_resources_removed": value.get("own_resources_removed", value.get("research_container_removed"))})
    return records


def research_pilot_evidence(project):
    rows = []
    for path in sorted((project / "logs").glob("research-loop-pilot-*/result.json")):
        value = read_json(path)
        if value.get("formal") is not False or value.get("hidden_or_final_evaluation") is not False:
            raise ValueError("engineering report only accepts explicitly non-hidden research pilots")
        fields = ("status", "task", "condition", "study_phase", "model_requested", "model_run_started", "formal",
                  "research_budget_seconds", "max_evaluations", "model_wall_seconds", "cost_usd")
        registry = value.get("registry") or {}
        usage = value.get("model_usage") or {}
        rows.append({"run_id": path.parent.name, "evidence": path.relative_to(project).as_posix(),
                     "evidence_sha256": file_hash(path), **{key: value.get(key) for key in fields},
                     "registered_evaluations": len(registry.get("evaluations", [])),
                     "first_id": registry.get("first_id"), "final_id": registry.get("final_id"),
                     "selection_reason": registry.get("selection_reason"),
                     "input_tokens": usage.get("n_input_tokens"), "cached_tokens": usage.get("n_cache_tokens"),
                     "output_tokens": usage.get("n_output_tokens"), "own_resources_removed": value.get("own_resources_removed")})
    return rows


def export_report(project, calibration, data):
    project, calibration, data = map(lambda p: Path(p).resolve(), (project, calibration, data))
    original_hash = file_hash(calibration)
    source = read_json(calibration)
    if source.get("final_test_scores_accessed") is not False:
        raise ValueError("report requires explicitly calibration-only source; hidden results are not read")
    if source.get("status") not in ("local_calibration_not_formal_freeze", "stopped_for_trusted_or_infrastructure_failure"):
        raise ValueError("unexpected calibration source status")
    run_id = calibration.parent.name
    run_rows, case_rows, comparisons = [], [], []
    for method in source["methods"]:
        result, task, name = method["result"], method["task"], method["method"]
        worker = result.get("worker", {})
        common = {"run_id": run_id, "dataset": data.name, "split": "author-calibration",
                  "task": task, "method": name, "repeat": 1, "formal": False,
                  "source_hash": method["source_hash"], "input_hash": method["input_hash"],
                  "judge_hash": source["judge_hash"], "image": source["image"], "model": None,
                  "condition": "author_baseline", "cost_usd": None}
        row = {**common, "fixed_reference": method["fixed_reference"],
               **{key: result.get(key) for key in ("attempt_status", "evaluation_status", "artifact_valid", "scientific_pass",
                                                    "performance_status", "passed", "total", "reward", "score", "judge_wall_seconds")},
               **{key: worker.get(key) for key in ("execution_wall_seconds", "total_wall_seconds", "cpu_seconds", "memory_peak_bytes", "formal_timing")},
               "result_path": (calibration.parent / task / name / "result.json").relative_to(project).as_posix()}
        run_rows.append(row)
        cases = result.get("cases", [])
        for case in cases:
            case_rows.append({**common, "case_id": case["id"], **{key: val for key, val in case.items() if key != "id"},
                              "attempt_status": result.get("attempt_status"), "result_path": row["result_path"]})
        maxima = {key: max((case[key] for case in cases if case.get(key) is not None), default=None)
                  for key in ("E_init", "E_forward", "E_roll", "E_field", "K", "max_relative_residual", "max_solution_error")}
        comparisons.append({"task": task, "method": name, "fixed_reference": method["fixed_reference"],
                            "passed": result.get("passed"), "total": result.get("total"), "score": result.get("score"),
                            "maxima": maxima, "failed_case_ids": [case["id"] for case in cases if not case["scientific_pass"]]})
    case_fields = ["run_id", "dataset", "split", "task", "method", "condition", "model", "repeat", "case_id", "level",
                   "formal", "attempt_status", "artifact_valid", "scientific_pass", "evaluation_status", "performance_status",
                   "score", "E_init", "E_forward", "E_roll", "E_field", "K", "rollout_errors", "integration_status",
                   "E_res", "E_sol", "max_relative_residual", "max_solution_error", "reason", "source_hash", "input_hash",
                   "judge_hash", "image", "cost_usd", "result_path"]
    run_fields = ["run_id", "dataset", "split", "task", "method", "condition", "model", "repeat", "formal", "fixed_reference",
                  "attempt_status", "artifact_valid", "scientific_pass", "evaluation_status", "performance_status", "passed",
                  "total", "reward", "score", "execution_wall_seconds", "total_wall_seconds", "judge_wall_seconds", "cpu_seconds",
                  "memory_peak_bytes", "formal_timing", "cost_usd", "source_hash", "input_hash", "judge_hash", "image", "result_path"]
    _csv(project / "results/cases/calibration.csv", case_rows, case_fields)
    _csv(project / "results/runs/calibration.csv", run_rows, run_fields)
    write_json(project / "results/comparisons/calibration-summary.json", {
        "source": calibration.relative_to(project).as_posix(), "source_sha256": original_hash,
        "formal": False, "independent_model_sessions": 0, "methods": comparisons})
    generation = generation_evidence(project, data)
    runtime = []
    current_worker_hash = file_hash(project / "runner/worker.py")
    for path in sorted((project / "logs").glob("runtime-probes-*/summary.json")):
        value = read_json(path)
        workers = sorted({read_json(provenance).get("worker_source_sha256")
                          for provenance in path.parent.glob("*/provenance.json")} - {None})
        runtime.append({"evidence": path.relative_to(project).as_posix(), "sha256": file_hash(path),
                        "passed": value["passed"], "total": value["total"],
                        "worker_source_hashes": workers,
                        "matches_current_worker_source": workers == [current_worker_hash],
                        "failed": [row["probe"] for row in value["probes"] if not row["passed"]]})
    model_rows = model_evidence(project)
    _csv(project / "results/runs/model-pilots.csv", model_rows,
         ["run_id", "attempt_status", "parent_attempt", "study_phase", "formal", "model_requested", "input_tokens", "cached_tokens",
          "output_tokens", "model_wall_seconds", "cost_usd", "network_status", "resource_status", "source_hash", "research_container_removed", "evidence", "evidence_sha256"])
    pilot_wj_path = project / "logs/pilot-model-registry-wj-001/result.json"
    pilot_wj = read_json(pilot_wj_path) if pilot_wj_path.exists() else None
    bridge_path = project / "logs/bridge-runtime-001/result.json"
    bridge = read_json(bridge_path) if bridge_path.exists() else None
    research_pilots = research_pilot_evidence(project)
    if research_pilots:
        _csv(project / "results/runs/research-pilots.csv", research_pilots, list(research_pilots[0]))
    stage = {"generated_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
             "formal": False, "calibration_source_sha256": original_hash, "calibration_methods": len(run_rows),
             "calibration_source": calibration.relative_to(project).as_posix(),
             "calibration_case_rows": len(case_rows), "generation": generation, "runtime_probes": runtime,
             "current_worker_source_sha256": current_worker_hash, "engineering_probes": engineering_evidence(project),
             "model_pilots": model_rows, "pilot_model_wj": pilot_wj,
             "research_pilots": research_pilots,
             "localhost_bridge": bridge,
             "final_test_scored": False, "formal_guidance_cells_completed": 0, "formal_research_sessions_completed": 0,
             "local_execution_authorized": True, "formal_resources_accepted": False,
             "test_evidence": [p.relative_to(project).as_posix() for p in sorted(
                 [p for p in (project / "logs").glob("*test*") if p.is_file()]
                 + list((project / "logs").glob("run-plan-*/tests.stdout.txt")))]}
    write_json(project / "results/stage-status.json", stage)
    write_results_document(project, comparisons, stage)
    if file_hash(calibration) != original_hash:
        raise RuntimeError("original calibration evidence changed during report export")
    return {"run_rows": len(run_rows), "case_rows": len(case_rows), "model_pilot_attempts": len(model_rows), "formal": False}


def write_results_document(project, comparisons, stage):
    indexed = {(row["task"], row["method"]): row for row in comparisons}
    heat = indexed.get(("heat", "tikhonov"), {}).get("maxima", {})
    ode = indexed.get(("ode", "fixed"), {}).get("maxima", {})
    poisson = indexed.get(("poisson", "lu"), {}).get("maxima", {})
    fmt = lambda value: "null" if value is None else f"{value:.5g}"
    lines = ["# 本机实施与校准结果", "", "当前证据支持三任务生成/QC、作者基线和 W/J 本机功能；正式三组研究及 final-test 成绩尚未完成。所有表格保留失败，不把实例数量当作研究会话数量。", "",
             "## 作者校准", "", f"来源：[原始完整结果](../{stage['calibration_source']})。每种方法只跑一次 author-calibration 批次，每批12例、每档4例；下表给出全部方法和分母。校准数值可解性不能替代未见测试或正式资源验收。", "",
             "| 任务 | 方法 | 通过数 | 连续分 |", "|---|---|---:|---:|"]
    for row in comparisons:
        score = "null（性能未验收）" if row["score"] is None else f"{row['score']:.3f}"
        label = METHOD_LABELS.get((row["task"], row["method"]), row["method"])
        lines.append(f"| {row['task']} | {label} | {row['passed']}/{row['total']} | {score} |")
    lines += ["", "前向扩散会掩盖不稳定高频，因此不能把低观测/前向残差当作逆恢复成功。T2 合法但超出 K<=10 紧凑性限制的模型保留为0分。失败实例和原始误差均未删除。", "",
              f"固定 Tikhonov 的最大初场/前向误差为 {fmt(heat.get('E_init'))}/{fmt(heat.get('E_forward'))}。固定 SG/STLSQ 的最大 rollout/field 误差为 {fmt(ode.get('E_roll'))}/{fmt(ode.get('E_field'))}。LU 的最大残差/解误差为 {fmt(poisson.get('max_relative_residual'))}/{fmt(poisson.get('max_solution_error'))}。完整逐例误差、K、状态及失败ID见导出表和原始JSON。", "",
              "T3 三种方法数值均通过；这里没有冻结性能 profile，也没有执行要求的三组独占 B,C,C,B,B,C 校准。日志中的执行墙钟含 Docker exec 开销且运行于共享宿主，正式 S3、speedup 门槛和任务 reward 保持 null。不要据单次墙钟比值发布加速结论。", "",
              f"可机读表：[{stage['calibration_case_rows']}个方法×实例记录](../results/cases/calibration.csv)、[{stage['calibration_methods']}个批次记录](../results/runs/calibration.csv)、[方法汇总及失败ID](../results/comparisons/calibration-summary.json)。CSV 中未知值为字面量 `null`；成本未估算。", "", "## 数据与复现证据", "",
              f"当前生成 {stage['generation']['case_count']} 例，{stage['generation']['qc_passed']} 例通过预声明 GT QC。每任务为6 dev、12 calibration、12 final；36个 final 实例仅做生成与GT检查，未读取求解成绩。", "",
              "[同熵重建证据](../freezes/data-reproduction-local.json)记录同一固定Linux镜像重建90例，369个公开输入文件逐字节一致。生成器期间补充了来源快照和重复审计，但没有改变数据公式或随机流；重建来源保存在 `authoring/data/v0.3-local-reproduced/private/generator-code/`。这不是第二台独立机器上的重跑。", "",
              "T3 共有21个独立算子：10个易档实例共用固定 A、RHS 独立，20个中/难档 A 不同。T1易档全保留mask、固定网格、T2固定时间/初值以及T3逐档metadata是设计常量，不能冒充独立随机矩阵。", "", "## 运行时与模型 smoke", "",
              "W运行时第一轮11项通过10项，发现日志洪泛误分类；原失败保留。修复后对正常路径、洪泛、超时和后台管道四项重跑，4/4通过。两轮共15个专用探针容器已移除，原8个服务仍运行；参见 [第一轮](../logs/runtime-probes-001/summary.json)、[回归](../logs/runtime-probes-002/summary.json)及[协议边界](protocol.md)。", "",
              "真实模型 pilot 保留两个 attempt：第一次在镜像构建阶段失败，未调用模型；第二次通过 Harbor 内置 Pi 调用配置的 DeepSeek 兼容端点，读取公共形状并写出刻意要求的零解程序。它用于链路测试，不是自主求解成功，也不属于 G1/G2/G3 正式格。输入8924 token（含缓存6528）、输出625 token，模型阶段约11.84秒，金额未知为null。R使用2 CPU/2 GiB且网络未限定，仅属于诊断配置。参见 [原始失败](../logs/model-smoke-20261022-01/result.json)、[模型生成源码](../logs/model-smoke-20261022-02/result.json)和[集成说明](harbor-integration.md)。", ""]
    if stage["pilot_model_wj"] is None:
        lines += ["模型源码的后续 registry→W→J 检查尚未在本报告读取到完整 result.json；不能把保留源码直接算作独立评分已完成。", ""]
    else:
        pilot = stage["pilot_model_wj"]
        lines += [f"模型源码的 registry→W→J 原始结果已保存于 [pilot-model-registry-wj-001](../logs/pilot-model-registry-wj-001/result.json)。状态为 `{pilot.get('status')}`，first/final为 `{pilot.get('first_id')}` / `{pilot.get('final_id')}`，共 {len(pilot.get('repeats', []))} 次清洁重放，reward={pilot.get('reward')}、score={pilot.get('score')}。合法零解得到0分证明独立评分链路；没有研究迭代，也不能计入正式三组矩阵。", ""]
    if stage.get("localhost_bridge") is not None:
        bridge = stage["localhost_bridge"]
        passed = sum(probe.get("passed") is True for probe in bridge.get("probes", []))
        lines += [f"[localhost受控桥探针](../logs/bridge-runtime-001/result.json)有 {passed}/{len(bridge.get('probes', []))} 项通过，包含真实W公开反馈、认证拒绝、路径逃逸、快照后改写与finalize。它是宿主本地接口验证，不是R网络allowlist或完整研究闭环。", ""]
    probes = stage["engineering_probes"]
    lines += ["## 研究容器与文件桥", "", "用户已授权继续本机功能开发；该授权不改变正式4 vCPU/4 GiB和30分钟/20次评估预算。新增探针继续标记 `formal=false`，不调用模型，也不读取隐藏成绩。", "",
              "| 保留的运行 | 记录状态 | 通过项 |", "|---|---|---:|"]
    for row in probes["research_network"] + probes["file_bridge"]:
        count = "—" if row["total"] is None else f"{row['passed']}/{row['total']}"
        lines.append(f"| [{row['run_id']}](../{row['evidence']}) | `{row['status']}` | {count} |")
    network = next((row for row in probes["research_network"] if row["run_id"] == "research-network-probe-005"), None)
    if network is not None and network["status"] == "functional_probe_passed":
        lines += ["", "网络005实测研究进程为UID1000、无capabilities、no-new-privileges；模型域名仍可连接，example.com与直接IP两个对照被阻断，标记socket与raw socket创建均EPERM。该探针使用1 CPU/1 GiB、无模型调用，且未执行Pi安装；它没有覆盖所有DNS/TLS绕过或未来CHOWN-only启动配置。此前构建/插件失败及root配置004均保留，详见[集成说明](harbor-integration.md)。"]
    file_bridge = next((row for row in probes["file_bridge"] if row["run_id"] == "file-bridge-runtime-001"), None)
    if file_bridge is not None and file_bridge["status"] == "functional_probe_passed":
        lines += ["", "文件桥001的9项检查包含：6例公开输入逐文件匹配，研究用户不能改写helper/反馈，路径逃逸被拒绝且消耗额度，已登记快照在独立W执行，反馈无隐藏指标，R事后改写不影响快照，finalize与first/final保留。这里没有模型调用；真实Pi研究循环须由其自己的完整结果验收。"]
    matching = [row for row in stage["runtime_probes"] if row["matches_current_worker_source"]]
    if matching:
        lines += ["", "与本报告生成时worker源码哈希一致的回归：" + "；".join(
            f"[{Path(row['evidence']).parent.name}](../{row['evidence']}) {row['passed']}/{row['total']}"
            for row in matching) + "。这些回归只覆盖各自列出的探针，旧轮的覆盖范围仍按旧源码版本报告。"]
    if stage["research_pilots"]:
        lines += ["", "模型研究循环pilot的当前记录如下；未结束或失败均不计成功，所有运行都不是正式研究格：", "",
                  "| 运行 | 当前记录状态 | 已登记评估 / 最终选择 | 预算秒/评估上限 |", "|---|---|---|---:|"]
        for row in stage["research_pilots"]:
            lines.append(f"| [{row['run_id']}](../{row['evidence']}) | `{row['status']}` | {row['registered_evaluations']} / `{row['selection_reason']}` | {row['research_budget_seconds']}/{row['max_evaluations']} |")
        lines += ["", "pilot的缩短预算用于接线检验，不更改正式会话的1800秒/20次预算。当前状态和证据hash同时写入[研究pilot表](../results/runs/research-pilots.csv)。"]
    lines += ["", "旧W探针只证明各自 `provenance.json` 所记源码。stage-status同时保存当前worker哈希和是否与各轮探针匹配；不能把旧版本通过记录直接算作后续截止时间/资源修订的回归。公开T3 Jacobi-CG比较程序已加入共同任务环境，仅用A/RHS，内部时间为诊断；正式比较仍需可信W完整计时。", ""]
    lines += ["自动汇总见 [stage-status.json](../results/stage-status.json)，模型attempt表见 [model-pilots.csv](../results/runs/model-pilots.csv)。测试数量随新增检查变化，以实际测试日志与当前运行输出为准，本报告不把旧计数固定成验收结论。", "", "## 未完成的验收", "",
              "正式资源和完整Pi研究生命周期、固定模型参数/系统提示/有效工具配置及各任务freeze、至少9格（主目标15会话）、first/final隐藏重放、T3性能profile与独占计时、独立干净环境复现、个人GitHub实际发布仍未完成。正式研究当前为0格、0会话；final-test仅做GT QC，未查看任何求解成绩。15次分块运行清单只生成draft，遇到未证参数、缺freeze或哈希漂移会拒绝启动。详见 [README](../README.md)和[局限](limitations.md)。", ""]
    (project / "docs/results.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    print(json.dumps(export_report(args.project, args.calibration or args.project / "results/calibration-local-001/summary.json",
                                   args.data or args.project / "authoring/data/v0.3-local"), ensure_ascii=False))
