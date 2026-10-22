"""Trusted Docker worker. Never mount GT, judge code, credentials or Docker socket."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import subprocess
import selectors
import threading
import time
import uuid
from .artifact_gate import ArtifactError, extract_tar, admit_outputs, regular_tree, MAX_SOURCE
from .common import write_json

class InfrastructureError(RuntimeError):
    pass

class BudgetTimeout(TimeoutError):
    """The enclosing research deadline expired, independently of correctness."""
    pass

def docker(*args,timeout=30,check=True):
    proc=subprocess.run(["docker",*map(str,args)],capture_output=True,text=True,timeout=timeout)
    if check and proc.returncode:
        raise InfrastructureError(proc.stderr.strip() or proc.stdout.strip())
    return proc

def inspect(container):
    return json.loads(docker("inspect",container).stdout)[0]

def bounded_execution(command,run_dir,budget,container):
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    selector=selectors.DefaultSelector()
    selector.register(process.stdout,selectors.EVENT_READ,"stdout")
    selector.register(process.stderr,selectors.EVENT_READ,"stderr")
    streams={name:(run_dir/(name+".txt")).open("wb") for name in ("stdout","stderr")}
    deadline=time.monotonic()+budget
    total=0
    status=None
    def stop_container():
        try:
            docker("kill",container,timeout=5,check=False)
        except (OSError,subprocess.TimeoutExpired):
            pass  # run_worker also removes this unique container in its finally.
    try:
        while selector.get_map():
            if time.monotonic()>=deadline:
                status="timeout"
                break
            for key,_ in selector.select(min(.1,max(0,deadline-time.monotonic()))):
                data=os.read(key.fileobj.fileno(),65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                remaining=max(0,4*1024**2-total)
                streams[key.data].write(data[:remaining])
                total+=len(data)
                if total>4*1024**2:
                    status="log_limit"
                    break
            if status:
                break
        if status:
            stop_container()
            # The Docker client may itself be blocked writing a full local pipe.
            # Terminate that client after the daemon has killed the workload.
            if process.poll() is None:
                process.kill()
        try:
            code=process.wait(timeout=max(.01,deadline-time.monotonic()) if not status else 1)
        except subprocess.TimeoutExpired:
            status="timeout"
            stop_container()
            if process.poll() is None:
                process.kill()
            code=process.wait(timeout=1)
        return status or ("completed" if code==0 else "candidate_failed"),code,total
    finally:
        if process.poll() is None:
            try:
                stop_container()
            finally:
                process.kill()
                process.wait(timeout=1)
        selector.close()
        process.stdout.close()
        process.stderr.close()
        for stream in streams.values():
            stream.close()

def run_worker(task, source, inputs, run_dir, image, *, method=None, timeout=None):
    started_at=time.monotonic()
    if timeout is not None and (not math.isfinite(timeout) or timeout<=0):
        raise ValueError("worker timeout must be finite and positive")
    deadline=None if timeout is None else started_at+timeout
    def remaining():
        value=30.0 if deadline is None else deadline-time.monotonic()
        if value<=0:
            raise BudgetTimeout("research deadline expired")
        return value
    def control(*args,timeout=30,check=True):
        try:
            return docker(*args,timeout=min(timeout,remaining()),check=check)
        except subprocess.TimeoutExpired as exc:
            if deadline is not None and time.monotonic()>=deadline:
                raise BudgetTimeout("research deadline expired during Docker control") from exc
            raise
    def container_info():
        return json.loads(control("inspect",name).stdout)[0]
    source,inputs,run_dir=map(lambda x:Path(x).resolve(),(source,inputs,run_dir))
    run_dir.mkdir(parents=True,exist_ok=False)
    regular_tree(source,MAX_SOURCE)
    name="sciresearch-w-"+uuid.uuid4().hex[:12]
    execution_limit=60 if task=="poisson" else 120
    budget=min(timeout if timeout is not None else execution_limit,execution_limit)
    config=["create","--name",name,"--label","sciresearch.project=benchmark-v0.3","--network","none","--cpus","1","--memory","4g","--memory-swap","4g","--pids-limit","128","--cap-drop","ALL","--security-opt","no-new-privileges","--read-only","--user","65534:65534","--ipc","private","--tmpfs","/output:rw,noexec,nosuid,nodev,size=268435456,mode=1777","--tmpfs","/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777","--shm-size","1m","--mount",f"type=bind,src={source},dst=/submission,readonly","--mount",f"type=bind,src={inputs},dst=/input,readonly"]
    for var in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","VECLIB_MAXIMUM_THREADS","NUMEXPR_NUM_THREADS"):
        config.extend(["--env",f"{var}=1"])
    config.extend([image,"sleep","infinity"])
    result={"attempt_status":"infrastructure_failed","artifact_valid":False,"scientific_pass":False,"evaluation_status":"not_evaluated","performance_status":"not_measured","image":image,"timeout_seconds":budget,"research_timeout_seconds":timeout,"budget_timeout":False,"timing_scope":"host Docker exec request through main process/pipe completion; process quiescence reported separately; diagnostic only","formal_timing":False}
    created=False
    deadline_stage="preparation"
    def record_budget_timeout(exc):
        result["budget_timeout"]=True
        result["budget_timeout_stage"]=deadline_stage
        if result["attempt_status"]=="infrastructure_failed":
            result["attempt_status"]="budget_timeout"
        result["reason"]=str(exc)
    wall_start=time.perf_counter()
    try:
        # Even a timed-out create may have reached the daemon; cleanup always
        # addresses this run's preselected, unique container name.
        created=True
        control(*config)
        control("start",name)
        info=container_info()
        write_json(run_dir/"container.json",{k:info[k] for k in ("Id","Image","HostConfig","Mounts","Config")})
        hc=info["HostConfig"]
        if hc["NetworkMode"]!="none" or hc["NanoCpus"]!=1000000000 or hc["Memory"]!=4*1024**3 or hc["MemorySwap"]!=hc["Memory"] or not hc["ReadonlyRootfs"]:
            raise InfrastructureError("Docker did not apply resource/security limits")
        cg_program="import json,pathlib; p=pathlib.Path('/sys/fs/cgroup'); print(json.dumps({n:(p/n).read_text() for n in ['cpu.max','cpu.stat','memory.max','memory.swap.max','memory.peak','memory.events','pids.max']}))"
        before=json.loads(control("exec",name,"python","-c",cg_program).stdout)
        write_json(run_dir/"cgroup_before.json",before)
        if before["memory.max"].strip()!=str(4*1024**3) or before["memory.swap.max"].strip()!="0" or before["pids.max"].strip()!="128":
            raise InfrastructureError("cgroup actual limits mismatch")
        cpu_quota,cpu_period=before["cpu.max"].split()
        if cpu_quota=="max" or int(cpu_quota)!=int(cpu_period):
            raise InfrastructureError("cgroup CPU quota mismatch")
        command=["docker","exec",name,"python","-B","/submission/solve.py","--input","/input","--output","/output","--seed","0"]
        if method is not None:
            command.extend(["--method",method])
        budget=execution_limit if deadline is None else min(execution_limit,remaining())
        result["timeout_seconds"]=budget
        deadline_stage="execution"
        start=time.perf_counter()
        result["attempt_status"],result["exit_code"],result["log_bytes_observed"]=bounded_execution(command,run_dir,budget,name)
        result["execution_wall_seconds"]=time.perf_counter()-start
        deadline_stage="post_execution"
        state=container_info()["State"]
        result["oom_killed"]=state["OOMKilled"]
        if state["Running"]:
            # Linux kill(-1) kills every permitted same-UID process except the caller and PID 1.
            # Candidate and descendants cannot change UID (no capabilities/no-new-privileges).
            # Then verify the only live process is the trusted container keepalive.
            reaper=control("exec",name,"python","-I","-c","import os,signal\ntry: os.kill(-1,signal.SIGKILL)\nexcept ProcessLookupError: pass",check=False)
            (run_dir/"reaper_stderr.txt").write_text(reaper.stderr)
            process_table=control("top",name,"-eo","pid,stat,comm",check=False)
            (run_dir/"processes_after_reap.txt").write_text(process_table.stdout)
            active=[line.split() for line in process_table.stdout.splitlines()[1:] if line.strip()]
            alive=[row for row in active if int(row[0])!=state["Pid"] and not row[1].startswith("Z")]
            if reaper.returncode or process_table.returncode or alive:
                result["attempt_status"]="candidate_resource_failure"
                result["reason"]="could not establish candidate-process termination"
                control("rm","-f",name)
                created=False
                return result
            result["candidate_processes_terminated"]=True
            result["processes_quiesced_at_seconds"]=time.perf_counter()-start
            after=json.loads(control("exec",name,"python","-I","-c",cg_program).stdout)
            write_json(run_dir/"cgroup_after.json",after)
            result["memory_peak_bytes"]=int(after["memory.peak"])
            stats=lambda text:dict(line.split() for line in text.strip().splitlines())
            result["cpu_seconds"]=(int(stats(after["cpu.stat"])["usage_usec"])-int(stats(before["cpu.stat"])["usage_usec"]))/1e6
            if int(stats(after["memory.events"])["oom_kill"])>0:
                result["oom_killed"]=True
                result["attempt_status"]="oom"
            if result["attempt_status"]=="completed":
                deadline_stage="artifact_transfer"
                with (run_dir/"copy_stderr.txt").open("wb") as err:
                    # Docker cp omits this engine's tmpfs contents; trusted tar reads the
                    # live mount after all candidate processes have been terminated.
                    transfer_budget=min(30,remaining())
                    copy=subprocess.Popen(["docker","exec",name,"/bin/tar","-C","/output","-cf","-","."],stdout=subprocess.PIPE,stderr=err)
                    transfer_expired=threading.Event()
                    def end_transfer():
                        transfer_expired.set()
                        try:
                            copy.kill()
                        except ProcessLookupError:
                            pass
                    transfer_timer=threading.Timer(transfer_budget if deadline is None else max(.001,min(transfer_budget,deadline-time.monotonic())),end_transfer)
                    transfer_timer.daemon=True
                    transfer_timer.start()
                    try:
                        extract_tar(copy.stdout,run_dir/"quarantine")
                        if copy.wait(timeout=min(transfer_budget,remaining()))!=0:
                            raise InfrastructureError("Docker output transfer failed")
                    except Exception as exc:
                        if deadline is not None and time.monotonic()>=deadline:
                            raise BudgetTimeout("research deadline expired during artifact transfer") from exc
                        if transfer_expired.is_set():
                            raise InfrastructureError("artifact transfer timed out") from exc
                        raise
                    finally:
                        transfer_timer.cancel()
                        if copy.poll() is None:
                            copy.kill()
                        copy.wait(timeout=1)
                        copy.stdout.close()
            # All processes are killed before quarantine can become scoring input.
            control("rm","-f",name)
            created=False
            result["all_processes_terminated"]=True
            if result["attempt_status"]=="completed":
                deadline_stage="artifact_admission"
                rows=admit_outputs(task,inputs,run_dir/"quarantine",run_dir/"artifacts")
                result["cases"]=rows
                result["artifact_valid"]=all(x["artifact_valid"] for x in rows)
                result["attempt_status"]="completed" if result["artifact_valid"] else "invalid_artifact"
                remaining()
        elif result["oom_killed"]:
            result["attempt_status"]="oom"
    except BudgetTimeout as exc:
        record_budget_timeout(exc)
    except ArtifactError as exc:
        result["attempt_status"]="invalid_artifact"
        result["reason"]=str(exc)
    except (InfrastructureError,subprocess.TimeoutExpired,OSError,ValueError) as exc:
        if deadline is not None and time.monotonic()>=deadline:
            record_budget_timeout(exc)
        else:
            result["attempt_status"]="infrastructure_failed"
            result["reason"]=str(exc)
    finally:
        if created:
            try:
                cleanup=docker("rm","-f",name,timeout=5,check=False)
                result["cleanup_status"]="completed" if cleanup.returncode==0 else "failed"
            except (subprocess.TimeoutExpired,OSError) as exc:
                result["cleanup_status"]="failed"
                result["cleanup_error"]=str(exc)
        result["total_wall_seconds"]=time.perf_counter()-wall_start
        write_json(run_dir/"worker.json",result)
    return result
