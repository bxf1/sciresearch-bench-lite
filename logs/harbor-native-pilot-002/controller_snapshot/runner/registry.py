"""Host-owned research records and snapshots, outside the research workspace."""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import time
from .artifact_gate import regular_tree, snapshot_source, MAX_SOURCE, MAX_FILES, ArtifactError
from .common import canonical, digest, read_json, write_json, tree_hashes

class Registry:
    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def create(cls, root, workspace, task, condition, budget_seconds=1800, max_evaluations=20):
        root = Path(root)
        workspace = Path(workspace).resolve(strict=True)
        if root.resolve().is_relative_to(workspace):
            raise ValueError("registry must be outside R workspace")
        root.mkdir(parents=True, exist_ok=False)
        write_json(root / "state.json", {"task":task,"condition":condition,"workspace":str(workspace),"started_at":time.time(),"budget_seconds":budget_seconds,"max_evaluations":max_evaluations,"evaluations":[],"first_id":None,"final_id":None,"finalization_invalid":False,"closed":False})
        return cls(root)

    def _event(self, kind, payload):
        log = self.root / "events.jsonl"
        previous = "0" * 64
        if log.exists():
            previous = __import__("json").loads(log.read_text().splitlines()[-1])["event_hash"]
        row = {"time":time.time(),"kind":kind,"payload":payload,"previous_hash":previous}
        row["event_hash"] = digest(canonical(row))
        with log.open("ab") as f:
            f.write(canonical(row) + b"\n")
            f.flush()
            os.fsync(f.fileno())

    def evaluate(self, relative_source, execute, *, prepare_source=None):
        with (self.root / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = read_json(self.root / "state.json")
            if state["closed"] or time.time() >= state["started_at"] + state["budget_seconds"]:
                raise ValueError("research deadline reached")
            if len(state["evaluations"]) >= state["max_evaluations"]:
                raise ValueError("evaluation budget exhausted")
            workspace = Path(state["workspace"])
            # Every accepted request consumes a slot, including invalid source or worker failure.
            candidate_id = f"candidate-{len(state['evaluations'])+1:03d}"
            row = {"id":candidate_id,"accepted_at":time.time(),"artifact_valid":False,"source_hash":None}
            state["evaluations"].append(row)
            write_json(self.root / "state.json", state)
            self._event("evaluate_accepted", {"id":candidate_id,"path":relative_source})
            try:
                if prepare_source is not None:
                    remaining = state["started_at"] + state["budget_seconds"] - time.time()
                    if remaining <= 0:
                        raise ArtifactError("research deadline reached before source preparation")
                    try:
                        relative_source = prepare_source(relative_source, candidate_id, remaining)
                    except Exception as exc:
                        raise ArtifactError("source preparation failed: " + type(exc).__name__ + ": " + str(exc)[:1024]) from exc
                    if time.time() >= state["started_at"] + state["budget_seconds"]:
                        raise ArtifactError("research deadline reached during source preparation")
                snapshot = self.root / "snapshots" / candidate_id
                snapshot_source(workspace, relative_source, snapshot)
                regular_tree(snapshot, MAX_SOURCE, MAX_FILES)
                hashes = tree_hashes(snapshot)
                row["source_hash"] = digest(canonical(hashes))
                write_json(self.root / "snapshots" / f"{candidate_id}.json", hashes)
                for p in snapshot.rglob("*"):
                    p.chmod(0o555 if p.is_dir() else 0o444)
                snapshot.chmod(0o555)
                remaining = max(0, state["started_at"] + state["budget_seconds"] - time.time())
                if remaining <= 0:
                    raise ArtifactError("research deadline reached while snapshotting")
                try:
                    row["result"] = execute(snapshot, candidate_id, remaining)
                except Exception as exc:
                    row["result"] = {"artifact_valid":False,"reason":str(exc),"attempt_status":"infrastructure_error","evaluation_status":"invalid","score":None}
                row["artifact_valid"] = bool(row["result"].get("artifact_valid",False))
                if row["artifact_valid"] and state["first_id"] is None:
                    state["first_id"] = candidate_id
            except (OSError,ValueError) as exc:
                row["result"] = {"artifact_valid":False,"reason":str(exc),"attempt_status":"submission_failed"}
            row["completed_at"] = time.time()
            write_json(self.root / "state.json",state)
            self._event("evaluate_completed",row)
            return row

    def finalize(self, candidate_id):
        with (self.root / ".lock").open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            state=read_json(self.root / "state.json")
            if state["closed"] or time.time() >= state["started_at"]+state["budget_seconds"]:
                raise ValueError("research is closed")
            exists=any(row["id"]==candidate_id and row["source_hash"] is not None and "completed_at" in row for row in state["evaluations"])
            if not exists:
                state["finalization_invalid"]=True
            else:
                state["final_id"]=candidate_id
            write_json(self.root / "state.json",state)
            self._event("finalize",{"id":candidate_id,"accepted":exists})
            if not exists:
                raise ValueError("finalize requires an evaluated ID from this run")

    def close(self, *, attempt_status=None, reason=None, evidence_sha256=None):
        """Record a host-controller outcome; no research bridge accepts these fields.

        Omitting the outcome preserves legacy nonformal callers. Once closed,
        the recorded outcome cannot be rewritten by a later call.
        """
        statuses={"completed","research_timeout","api_failed","infrastructure_failed","cancelled"}
        if attempt_status is not None and attempt_status not in statuses:
            raise ValueError("unknown trusted research outcome")
        if reason is not None and (not isinstance(reason,str) or len(reason)>2048):
            raise ValueError("outcome reason must be at most 2048 characters")
        if evidence_sha256 is not None and (not isinstance(evidence_sha256,str) or not __import__("re").fullmatch(r"[0-9a-f]{64}",evidence_sha256)):
            raise ValueError("outcome evidence must be a SHA256 digest")
        if attempt_status is None and (reason is not None or evidence_sha256 is not None):
            raise ValueError("outcome metadata requires an explicit status")
        with (self.root / ".lock").open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            state=read_json(self.root / "state.json")
            if state["closed"] and attempt_status is not None:
                existing=state.get("attempt_outcome",{})
                requested={"status":attempt_status,"reason":reason,"evidence_sha256":evidence_sha256}
                if any(existing.get(key)!=value for key,value in requested.items()):
                    raise ValueError("closed research outcome is immutable")
            if not state["closed"]:
                if attempt_status is not None:
                    state["attempt_status"]=attempt_status
                    state["attempt_outcome"]={"status":attempt_status,"reason":reason,
                                              "evidence_sha256":evidence_sha256,"recorded_at":time.time()}
                if state["finalization_invalid"]:
                    state["final_id"]=None
                    state["selection_reason"]="invalid_finalize"
                elif state["final_id"] is None:
                    valid=[r for r in state["evaluations"] if r["artifact_valid"]]
                    state["final_id"]=valid[-1]["id"] if valid else None
                    state["selection_reason"]="deadline_fallback" if valid else "no_valid_submission"
                else:
                    state["selection_reason"]="explicit_finalize"
                state["closed"]=True
                write_json(self.root / "state.json",state)
                self._event("closed",state)
            return state

    def verified_snapshot(self,candidate_id):
        if not __import__("re").fullmatch(r"candidate-\d{3}",candidate_id):
            raise ValueError("invalid candidate ID")
        path=self.root / "snapshots" / candidate_id
        expected=read_json(path.with_suffix(".json"))
        regular_tree(path, MAX_SOURCE, MAX_FILES)
        if tree_hashes(path)!=expected:
            raise RuntimeError("registered snapshot was modified")
        return path
