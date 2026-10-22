"""Build three Harbor task directories from an explicit public-only allowlist."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import tomllib
from harbor.models.task.config import TaskConfig
from runner.common import TASKS,VERSION,read_json,write_json,tree_hashes,digest,canonical
from runner.phase import validate_manifest

INPUTS={"heat":{"observations.csv","metadata.json","target_grid.npy"},"ode":{"train.npy","validation.npy","t.npy","train_initial.npy","validation_initial.npy","metadata.json"},"poisson":{"A.npz","rhs.npy","metadata.json"}}
OUTPUTS={"heat":{"name":"u0.npy","shape":[256]},"ode":{"name":"model.json","coefficients_shape":[10,2]},"poisson":{"name":"solution.npy","shape":["n*n",4]}}

def package(project,data_root,output):
    project,data_root,output=map(lambda p:Path(p).resolve(),(project,data_root,output))
    output.mkdir(parents=True,exist_ok=False)
    rows={}
    for task in TASKS:
        source=data_root/"inputs"/task/"public-dev"
        manifest=read_json(source/"manifest.json")
        validate_manifest(task,source,expected_split="public-dev")
        expected={"manifest.json"}
        for case in manifest["cases"]:
            expected.update(f"{case['path']}/{name}" for name in INPUTS[task])
        if set(tree_hashes(source))!=expected:
            raise ValueError(f"unexpected files in {task} public dev")
        root=output/task
        environment=root/"environment"
        environment.mkdir(parents=True)
        shutil.copytree(source,environment/"public-dev")
        public=environment/"public"
        public.mkdir()
        for name in (task+".py",):
            shutil.copyfile(project/"public"/name,public/name)
        if task == "poisson":
            shutil.copyfile(project/"public/poisson_compare.py",public/"poisson_compare.py")
        helpers = environment/"helpers"
        helpers.mkdir()
        for name in ("file_bench.py", "bridge_io.py", "export_source.py"):
            shutil.copyfile(project/"public"/name,helpers/name)
        trusted = environment/"trusted/runner"
        trusted.mkdir(parents=True)
        for name in ("__init__.py", "artifact_gate.py", "common.py"):
            shutil.copyfile(project/"runner"/name,trusted/name)
        (public/"bench").write_text('#!/bin/sh\nexec python -I /opt/bench/file_bench.py "$@"\n')
        (root/"instruction.md").write_text((project/"prompts"/task/"common.md").read_text())
        (environment/"Dockerfile").write_text('''FROM sciresearch-numeric:0.3.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends bash curl ca-certificates git coreutils xz-utils && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 --shell /bin/bash researcher && mkdir -p /workspace/.bench/requests /workspace/.bench/responses /input /opt/bench/public /logs/agent /logs/artifacts /run/bench-export && chmod 1777 /workspace && chmod 700 /run/bench-export && chown researcher:researcher /workspace/.bench/requests /logs/agent /logs/artifacts
COPY public-dev/ /input/
COPY public/ /opt/bench/public/
COPY helpers/ /opt/bench/
COPY trusted/ /opt/bench/trusted/
RUN chmod -R a-w /input /opt/bench && cp /opt/bench/public/bench /usr/local/bin/bench && chmod 755 /usr/local/bin/bench
ENV HOME=/home/researcher PYTHONPATH=/opt/bench
USER researcher
WORKDIR /workspace
CMD ["sleep", "infinity"]
''')
        config=f'''schema_version = "1.4"
artifacts = [{{source = "/logs/artifacts", exclude = ["*", "**/*"]}}]

[task]
name = "sciresearch-lite/{task}"
description = "v0.3 {task} research task; requires trusted research controller and custom verifier"
authors = []
keywords = ["scientific-computing", "research"]

[agent]
timeout_sec = 1800.0
user = "researcher"
network_mode = "allowlist"
allowed_hosts = ["api.deepseek.com"]

[environment]
network_mode = "public"
build_timeout_sec = 600.0
cpus = 4
memory_mb = 4096
storage_mb = 1024
workdir = "/workspace"
mcp_servers = []

[verifier]
environment_mode = "separate"
timeout_sec = 1200.0
network_mode = "no-network"

[verifier.environment]
network_mode = "no-network"
docker_image = "sciresearch-numeric:0.3.0"
cpus = 1
memory_mb = 4096
workdir = "/tmp"
'''
        TaskConfig.model_validate(tomllib.loads(config))
        (root/"task.toml").write_text(config)
        tests=root/"tests"
        tests.mkdir()
        (tests/"test.sh").write_text('#!/bin/sh\necho "This task requires runner.harbor_verifier:ResearchReplayVerifier and a closed host registry; default verification is disabled." >&2\nexit 2\n')
        (tests/"test.sh").chmod(0o755)
        contract={"contract_version":VERSION,"task":task,"entrypoint":"python solve.py --input /input --output /output --seed 0","case_path":"cases/<id>","output":OUTPUTS[task],"numeric_format":"little-endian binary64; finite real values; no pickle/object/complex","max_source_bytes":20*1024**2,"max_source_files":1000,"max_source_entries":2000,"max_path_depth":32,"max_output_bytes":256*1024**2,"max_tmp_bytes":64*1024**2,"max_registered_evaluations":20,"research_seconds":1800,"worker_seconds":60 if task=="poisson" else 120,"research_feedback_split":"public-dev only","status":"prepared_not_frozen","research_bridge":"host FileBridge polls bounded requests under /workspace/.bench; controller must start it before Pi","artifact_transfer":"only trusted W outputs can enter J; automatic Harbor research artifacts excluded"}
        write_json(root/"contract.json",contract)
        (root/"README.md").write_text(f"# {task}\n\nPrepared Harbor task package. This is not a completed formal trial. Public build context contains only the six dev inputs and public checker/client. Use the trusted controller, register evaluate/finalize, close research, then configure `runner.harbor_verifier:ResearchReplayVerifier`. The default test.sh intentionally fails so generic Harbor invocation cannot emit an unverified reward. G1/G2/G3 guidance comes from the separate prompts directory. Final data, generator, GT and baselines are absent.\n")
        rows[task]={"public_input_hashes":tree_hashes(source),"build_context_hashes":tree_hashes(environment),"config_sha256":digest(config.encode())}
    write_json(output/"package-manifest.json",{"version":VERSION,"status":"prepared_not_frozen","tasks":rows})
    return rows

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--data",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    package(Path(__file__).resolve().parents[1],a.data,a.output)
