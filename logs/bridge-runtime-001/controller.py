"""Explicit opt-in localhost bridge + real worker probe; never runs under pytest."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import secrets
import shutil
import threading
import urllib.error
import urllib.request
from runner.bridge import serve
from runner.common import canonical,digest,read_json,tree_hashes,write_json,file_hash
from runner.registry import Registry
from runner.worker import docker

def run(output):
    project=Path(__file__).resolve().parents[1]
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    workspace=output/"workspace"
    shutil.copytree(project/"baselines/heat",workspace/"candidate")
    registry=Registry.create(output/"registry",workspace,"heat","pilot-bridge",budget_seconds=120,max_evaluations=3)
    inputs=project/"authoring/data/pilot-smoke/inputs/heat/pilot-smoke"
    image=json.loads(docker("image","inspect","sciresearch-numeric:0.3.0").stdout)[0]["Id"]
    token=secrets.token_hex(32)
    server=serve(registry,"heat",inputs,image,token)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url=f"http://127.0.0.1:{server.server_port}"
    rows=[]
    def request(action,body,authorized=True):
        request=urllib.request.Request(url+action,data=json.dumps(body).encode(),headers={"Authorization":"Bearer "+(token if authorized else "wrong-token")},method="POST")
        try:
            with urllib.request.urlopen(request,timeout=130) as response:
                return response.status,json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raw=exc.read().decode()
            try: raw=json.loads(raw)
            except ValueError: pass
            return exc.code,raw
    try:
        status,body=request("/evaluate",{"path":"candidate"},False)
        rows.append({"probe":"wrong_token","passed":status==403,"status":status})
        status,body=request("/evaluate",{"path":"candidate","shell":"touch /tmp/forbidden"})
        rows.append({"probe":"extra_command_field","passed":status==400,"status":status})
        status,body=request("/evaluate",{"path":"../escape"})
        rows.append({"probe":"path_escape_consumes_slot_without_execution","passed":status==200 and body["feedback"]["attempt_status"]=="submission_failed","response":body})
        status,body=request("/evaluate",{"path":"candidate"})
        candidate_id=body["candidate_id"]
        rows.append({"probe":"real_evaluate","passed":status==200 and body["feedback"]["artifact_valid"],"response":body})
        forbidden=("E_init","E_forward","u0_true","coefficients.npy","root_entropy","scientific_pass")
        rows.append({"probe":"public_feedback_no_hidden_fields","passed":all(key not in json.dumps(body) for key in forbidden)})
        expected=body["source_hash"]
        path=workspace/"candidate/solve.py"
        path.write_text(path.read_text()+"\n# Research workspace mutation after evaluation.\n")
        actual=digest(canonical(tree_hashes(registry.verified_snapshot(candidate_id))))
        rows.append({"probe":"workspace_mutation_does_not_change_registered_source","passed":actual==expected})
        status,body=request("/finalize",{"candidate_id":candidate_id})
        rows.append({"probe":"finalize_evaluated_id","passed":status==200,"response":body})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    state=registry.close()
    result={"formal":False,"status":"passed" if all(row["passed"] for row in rows) else "failed","scope":"localhost authenticated bridge to trusted registry and isolated W public feedback only; not an R-container network test","controller_sha256":file_hash(__file__),"first_id":state["first_id"],"final_id":state["final_id"],"registered_requests":len(state["evaluations"]),"probes":rows}
    write_json(output/"result.json",result)
    shutil.copyfile(__file__,output/"controller.py")
    print(json.dumps({k:v for k,v in result.items() if k!="probes"}))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True,type=Path)
    run(parser.parse_args().output)
