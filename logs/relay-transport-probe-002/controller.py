from pathlib import Path
import asyncio,json,uuid
from runner.common import file_hash,write_json
from runner.relay_transport import start_relay,relay_overlay,lock_and_probe,read_status,cleanup_relay
from runner.verify_pilot import cleanup_environment
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig,NetworkMode,NetworkPolicy
from harbor.models.trial.paths import TrialPaths

async def main():
    root=Path.cwd()
    output=root/'logs/relay-transport-probe-002'
    output.mkdir(exist_ok=False)
    (output/'controller.py').write_bytes(Path(__file__).read_bytes())
    admission=None
    environment=None
    session='bench-relay-probe-'+uuid.uuid4().hex[:12]
    result={'formal':False,'model_calls':0,'session_id':session,'controller_sha256':file_hash(__file__),
            'tool_hashes':{name:file_hash(root/name) for name in ('runner/relay_transport.py','runner/model_relay.py')},'status':'starting'}
    try:
        admission=await asyncio.to_thread(start_relay,root/'build'/('relay-private-'+uuid.uuid4().hex[:12]),image='sciresearch-numeric:0.3.0',session_seconds=600)
        paths=TrialPaths(output/'harbor-trial');paths.mkdir()
        overlay=relay_overlay(admission)
        overlay['services']['main']={'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'mem_limit':'256m','memswap_limit':'256m','pids_limit':64}
        overlay['services']['harbor-docker-egress-control-sidecar'].update(cpus=.25,mem_limit='128m',memswap_limit='128m')
        write_json(output/'overlay.json',overlay)
        environment=DockerEnvironment(environment_dir=root/'environment',environment_name='relay-probe',session_id=session,
            trial_paths=paths,task_env_config=EnvironmentConfig(docker_image='sha256:6619dd1526ec8d635d0e57d068dc3e750821ddd82443d44777fe847340944bdb',cpus=1,memory_mb=256,workdir='/workspace'),
            network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC),phase_network_policies=[NetworkPolicy(network_mode=NetworkMode.ALLOWLIST,allowed_hosts=[admission['relay_ip']])],
            extra_docker_compose=[output/'overlay.json'],auto_mounting=False,enable_environment_dir_upload=False,cpu_enforcement_policy='limit',memory_enforcement_policy='limit')
        await asyncio.wait_for(environment.start(force_build=False),180)
        result['network']=await lock_and_probe(environment,admission,output/'network')
        result['relay_status']=await asyncio.to_thread(read_status,admission)
        assert result['relay_status']['request_count']==0
        result['status']='passed'
    except Exception as exc:
        result.update(status='failed',error=f'{type(exc).__name__}: {exc}')
    finally:
        if environment:
            result['environment_cleanup']=await cleanup_environment(environment,session)
            if result['environment_cleanup']['cleanup_errors']:result['status']='cleanup_failed'
        if admission:
            result['relay_cleanup']=await asyncio.to_thread(cleanup_relay,admission)
            if not result['relay_cleanup']['all_removed'] or result['relay_cleanup']['errors']:result['status']='cleanup_failed'
            private=Path(admission['output_root'])
            import shutil
            for name in ('startup.json','cleanup.json'):
                if (private/name).exists():shutil.copy2(private/name,output/('relay-'+name))
            if (private/'evidence').exists():shutil.copytree(private/'evidence',output/'relay-events')
        write_json(output/'result.json',result)
    print(json.dumps({'status':result['status'],'error':result.get('error'),'model_calls':0}))
    return result
if __name__=='__main__':
    result=asyncio.run(main())
    raise SystemExit(0 if result['status']=='passed' else 1)
