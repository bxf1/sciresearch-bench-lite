"""Host verifier import hook for the pinned Harbor 0.24.0 checkout.

Install Harbor's dependencies before importing this optional adapter. All
configuration comes from the trusted controller, never from a research file.
The controller must close the registry and satisfy the freeze/phase guard
before it asks Harbor to verify a run.
"""
from __future__ import annotations

import asyncio
import math
from pathlib import Path

from harbor.models.verifier.result import VerifierResult
from harbor.verifier.base import BaseVerifier

from .common import canonical, digest, read_json, tree_hashes, write_json
from .registry import Registry


class ResearchReplayVerifier(BaseVerifier):
    def __init__(self, *, registry_root: str, replay_config: dict, **kwargs):
        super().__init__(**kwargs)
        self.registry = Registry(Path(registry_root).resolve(strict=True))
        self.replay_config = dict(replay_config)

    async def _reject_automatic_artifacts(self):
        # Harbor transfers artifacts before constructing this verifier. A task
        # must explicitly exclude the convention dir and all other R artifacts.
        # Detect an unsafe transfer before any GT is passed to the replay runner.
        artifact_root = self.trial_paths.artifacts_dir
        if artifact_root.exists():
            for path in artifact_root.rglob("*"):
                if path == artifact_root / "manifest.json" and not path.is_symlink():
                    continue
                if path.is_symlink() or not path.is_dir():
                    raise RuntimeError("Research artifacts reached Harbor's automatic verifier transfer")
        result = await self.environment.exec(
            command="if [ -d /logs/artifacts ]; then find /logs/artifacts -mindepth 1 -print -quit; fi"
        )
        if result.return_code != 0 or (result.stdout or "").strip():
            raise RuntimeError("Harbor verifier artifact directory is not verified empty")

    async def verify(self) -> VerifierResult:
        diagnostics = {"adapter": "ResearchReplayVerifier", "evaluation_status": "invalid",
                       "first": None, "final": None, "reward": None, "score": None}
        output_path = self.trial_paths.verifier_dir / "research-replay.json"
        try:
            mode = self.task.config.verifier.environment_mode
            if getattr(mode, "value", mode) != "separate":
                raise RuntimeError("ResearchReplayVerifier requires separate verifier mode")
            state = read_json(self.registry.root / "state.json")
            if not state["closed"]:
                raise RuntimeError("Controller must close research before hidden replay")
            if self.registry.root.is_relative_to(Path(state["workspace"]).resolve()):
                raise RuntimeError("Registry is inside the research workspace")
            task = state["task"]
            if task not in ("heat", "ode", "poisson") or self.replay_config["task"] != task:
                raise RuntimeError("Replay task differs from the host registry")
            await self._reject_automatic_artifacts()
            if state.get("attempt_status") in ("api_failed", "infrastructure_failed"):
                raise RuntimeError("Research infrastructure attempt has no valid scientific evaluation")
            from .replay import replay_checkpoint

            rows = {row["id"]: row for row in state["evaluations"]}
            cache = {}
            for role in ("first", "final"):
                candidate_id = state[role + "_id"]
                if candidate_id is None:
                    diagnostics[role] = {"checkpoint_id": None, "reward": 0, "score": 0.0,
                                         "reason": state.get("selection_reason", "no_valid_submission"),
                                         "replay_count": 0}
                    continue
                row = rows.get(candidate_id)
                if row is None or "completed_at" not in row:
                    raise RuntimeError("Selected checkpoint is absent from completed host evaluations")
                if not row["artifact_valid"]:
                    diagnostics[role] = {"checkpoint_id": candidate_id, "reward": 0, "score": 0.0,
                                         "reason": "selected_evaluation_artifact_invalid", "replay_count": 0}
                    continue
                snapshot = self.registry.verified_snapshot(candidate_id)
                source_hash = digest(canonical(tree_hashes(snapshot)))
                if source_hash != row["source_hash"]:
                    raise RuntimeError("Snapshot manifest differs from the host registration hash")
                if source_hash in cache:
                    original = cache[source_hash]
                    diagnostics[role] = dict(original, checkpoint_id=candidate_id,
                                             reused_from=original["checkpoint_id"], replay_count=0)
                    continue
                repeats = []
                for repeat in range(1 if task == "poisson" else 3):
                    config = dict(self.replay_config)
                    config["output_root"] = Path(config["output_root"]) / candidate_id / f"repeat-{repeat + 1}"
                    result = await asyncio.to_thread(
                        replay_checkpoint, snapshot, candidate_id, source_hash, **config
                    )
                    if not isinstance(result, dict):
                        raise RuntimeError("Trusted replay returned a non-object result")
                    repeats.append(result)
                    self.registry.verified_snapshot(candidate_id)
                valid = all(result.get("evaluation_status") == "valid" for result in repeats)
                rewards = [result.get("reward") for result in repeats]
                scores = [result.get("score") for result in repeats]
                if any(value is not None and (not isinstance(value, (int, float)) or
                           not math.isfinite(value)) for value in rewards + scores):
                    raise RuntimeError("Trusted replay returned a nonfinite or nonnumeric score")
                if any(value is not None and value not in (0, 1) for value in rewards):
                    raise RuntimeError("Trusted replay returned a nonbinary reward")
                record = {"checkpoint_id": candidate_id, "source_hash": source_hash,
                          "repeats": repeats, "replay_count": len(repeats),
                          "evaluation_status": "valid" if valid else "invalid",
                          "reward": int(all(rewards)) if valid and None not in rewards else None,
                          "score": sum(scores) / len(scores) if valid and None not in scores else None}
                diagnostics[role] = record
                cache[source_hash] = record
            final = diagnostics["final"]
            diagnostics.update(reward=final["reward"], score=final["score"],
                               selection_reason=state.get("selection_reason"))
            diagnostics["evaluation_status"] = (
                "invalid" if any(record and record.get("evaluation_status") == "invalid"
                                 for record in (diagnostics["first"], diagnostics["final"])) else "valid"
            )
            if diagnostics["evaluation_status"] != "valid":
                diagnostics["reward"] = None
                diagnostics["score"] = None
        except Exception as exc:
            diagnostics.update(evaluation_status="invalid", reward=None, score=None,
                               reason=f"{type(exc).__name__}: {exc}")
        write_json(output_path, diagnostics)
        reward = diagnostics["reward"]
        if reward is None:
            return VerifierResult(rewards=None)
        write_json(self.trial_paths.reward_json_path, {"reward": reward})
        return VerifierResult(rewards={"reward": reward})
