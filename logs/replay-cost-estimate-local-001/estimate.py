"""Planning estimate from existing 12-case calibration, never final-test scores."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / "results/calibration-local-001/summary.json"
calibration = json.loads(source.read_text())
assert calibration["final_test_scores_accessed"] is False
rows = []
for item in calibration["methods"]:
    result = item["result"]
    assert result["total"] == 12
    worker = result["worker"]
    rows.append({"task": item["task"], "method": item["method"], "cases": 12,
                 "evaluation_status": result["evaluation_status"],
                 "worker_wall_seconds": worker["total_wall_seconds"],
                 "judge_wall_seconds": result["judge_wall_seconds"],
                 "combined_wall_seconds": worker["total_wall_seconds"] + result["judge_wall_seconds"]})
times = {(row["task"], row["method"]): row["combined_wall_seconds"] for row in rows}
checkpoint = {"heat": 3 * times["heat", "tikhonov"], "ode": 3 * times["ode", "fixed"],
              "poisson": 3 * (times["poisson", "jacobi"] + times["poisson", "lu"])}
scenarios = []
for label, sessions in (("minimum_9", {"heat": 3, "ode": 3, "poisson": 3}),
                        ("main_15", {"heat": 9, "ode": 3, "poisson": 3})):
    for distinct in (1, 2):
        scenarios.append({"label": label, "sessions": sessions, "distinct_checkpoints_per_session": distinct,
                          "checkpoint_replay_seconds_estimate": sum(sessions[t] * distinct * checkpoint[t] for t in sessions),
                          "fresh_W_J_batches": sum(sessions[t] * distinct * (6 if t == "poisson" else 3) for t in sessions),
                          "research_wall_budget_seconds": sum(sessions.values()) * 1800})
record = {"formal": False, "final_test_scores_accessed": False,
          "source": str(source.relative_to(root)), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
          "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "observed_methods": rows, "proxy_checkpoint_replay_seconds": checkpoint, "scenarios": scenarios,
          "three_T3_profile_groups_seconds_estimate": 3 * checkpoint["poisson"],
          "ode_per_checkpoint_rollout_timeout_ceiling_seconds": 3 * 12 * 4 * 5,
          "cost_usd": None,
          "limitations": ["Observed local calibration totals include W/J setup and transfer, not a formal performance measurement.",
                          "Fixed methods are runtime proxies; unknown agent candidates can approach the published timeout budgets.",
                          "Excludes research setup, model/provider failure, baseline reruns, profile instability reruns and scheduling overhead.",
                          "One distinct source means identical first/final reuse; two means both need the required replay protocol.",
                          "T3 six-batch protocol is counted once per distinct checkpoint, not wrapped in another triple repetition."]}
(Path(__file__).parent / "result.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({"checkpoint_seconds": checkpoint, "scenarios": scenarios}))
