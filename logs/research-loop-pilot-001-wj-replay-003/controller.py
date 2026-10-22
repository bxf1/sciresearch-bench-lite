"""Invoke the real Harbor verifier hook on a closed pilot registry.

This entry point accepts only pilot-smoke data. The Harbor environment is an
empty, disconnected orchestration environment; the replay runner separately
creates W and numeric-only J. It is not a complete Harbor SingleStepTrial.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import uuid

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
from harbor.models.task.task import Task
from harbor.models.trial.paths import TrialPaths
from .common import file_hash, read_json, write_json
from .harbor_verifier import ResearchReplayVerifier
from .phase import validate_manifest
from .registry import Registry
from .replay import prepare_judge
from .worker import docker


async def run(args):
    root=Path(__file__).resolve().parents[1]
    registry=Registry(args.registry.resolve(strict=True))
    state=read_json(registry.root/'state.json')
    if not state['closed']:
        raise ValueError('Research must be closed before independent pilot replay')
    task_name=state['task']
    inputs=args.data.resolve()/('inputs/'+task_name+'/pilot-smoke')
    truth=args.data.resolve()/('private/'+task_name+'/pilot-smoke')
    validate_manifest(task_name,inputs,expected_split='pilot-smoke')
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    (output/'controller.py').write_bytes(Path(__file__).read_bytes())
    paths=TrialPaths(output/'harbor-trial')
    paths.mkdir()
    image=json.loads(docker('image','inspect',args.image).stdout)[0]['Id']
    session='bench-verify-pilot-'+uuid.uuid4().hex[:12]
    overlay=output/'verifier-compose.json'
    write_json(overlay,{'services':{'main':{'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],
                'pids_limit':128,'mem_limit':'512m','memswap_limit':'512m'},
                'harbor-docker-egress-control-sidecar':{'cpus':.25,'mem_limit':'128m','memswap_limit':'128m'}}})
    environment=DockerEnvironment(environment_dir=root/'environment',environment_name='bench-verify-pilot',
        session_id=session,trial_paths=paths,task_env_config=EnvironmentConfig(docker_image=image,cpus=1,memory_mb=512,workdir='/tmp'),
        network_policy=NetworkPolicy(network_mode=NetworkMode.NO_NETWORK),extra_docker_compose=[overlay],
        cpu_enforcement_policy='limit',memory_enforcement_policy='limit',auto_mounting=False,enable_environment_dir_upload=False)
    result={'formal':False,'data_split':'pilot-smoke','session_id':session,'registry':str(registry.root),
            'registry_sha256':file_hash(registry.root/'state.json'),'controller_sha256':file_hash(__file__),
            'image_id':image,'score':None,'reward':None,'status':'starting',
            'parent_attempt':args.parent_attempt,
            'scope':'Real Harbor verifier hook; replay runner owns the separate W and numeric-only J.'}
    try:
        await asyncio.wait_for(environment.start(force_build=False),180)
        ids=docker('ps','-q','--filter','label=com.docker.compose.project='+session).stdout.split()
        info=json.loads(docker('inspect',*ids).stdout)
        write_json(output/'harbor-containers.json',[{k:c[k] for k in ('Id','Image','Config','HostConfig','Mounts')} for c in info])
        main=[c for c in info if c['Config']['Labels'].get('com.docker.compose.service')=='main']
        services={c['Config']['Labels'].get('com.docker.compose.service') for c in info}
        if len(main)!=1 or any(c['Mounts'] for c in info) or not services <= {'main','harbor-docker-egress-control-sidecar'}:
            raise RuntimeError('Unexpected Harbor verifier mounts or containers')
        if 'harbor-docker-egress-control-sidecar' in services:
            policy=await environment.service_exec('network-policy show',service='harbor-docker-egress-control-sidecar',timeout_sec=10)
            (output/'harbor-network-policy.txt').write_text((policy.stdout or '')+(policy.stderr or ''))
            if policy.return_code:
                raise RuntimeError('Cannot inspect Harbor orchestration network policy')
        config={'task':task_name,'input_root':inputs,'truth_root':truth,'output_root':output/'replays',
                'image':image,'judge_source_root':prepare_judge(root,root/'build/judge'),'profile':None}
        if task_name=='poisson':
            config['baseline_source']=root/'baselines/poisson'
        verifier=ResearchReplayVerifier(registry_root=str(registry.root),replay_config=config,
            task=Task(root/'tasks'/task_name),trial_paths=paths,environment=environment)
        returned=await verifier.verify()
        result['harbor_result']=returned.model_dump(mode='json')
        diagnostics=read_json(paths.verifier_dir/'research-replay.json')
        result.update(status='pilot_verifier_completed' if diagnostics['evaluation_status']=='valid' else 'pilot_evaluation_invalid',
                      score=diagnostics['score'],reward=diagnostics['reward'],diagnostics=diagnostics)
    except Exception as exc:
        result.update(status='pilot_verifier_failed',error=f'{type(exc).__name__}: {exc}')
    finally:
        try:
            await asyncio.wait_for(environment.stop(delete=True),90)
            result['orchestration_environment_removed']=True
        except Exception as exc:
            result['cleanup_error']=str(exc)
        write_json(output/'result.json',result)
    print(json.dumps({k:result.get(k) for k in ('status','error','reward','score','formal')}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('registry','data','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--image',default='sciresearch-numeric:0.3.0')
    p.add_argument('--parent-attempt')
    result=asyncio.run(run(p.parse_args()))
    if result['status']!='pilot_verifier_completed':
        raise SystemExit(1)
