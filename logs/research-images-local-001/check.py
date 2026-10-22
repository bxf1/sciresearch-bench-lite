import hashlib,json,os,subprocess
from pathlib import Path
from runner.common import tree_hashes,write_json
root=Path.cwd()
code='''import hashlib,json,os,pathlib
r=pathlib.Path('/input')
print(json.dumps({'uid':os.getuid(),'files':{str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file()},'status':pathlib.Path('/proc/self/status').read_text(),'helpers_writable':os.access('/opt/bench',os.W_OK),'responses_writable':os.access('/workspace/.bench/responses',os.W_OK),'socket_present':pathlib.Path('/var/run/docker.sock').exists()}))'''
rows=[]
for task in ('heat','ode','poisson'):
    tag=f'sciresearch-{task}-r:0.3.1'
    metadata=json.loads(subprocess.check_output(['docker','image','inspect',tag]))[0]
    command=['docker','run','--rm','--network','none','--cpus','1','--memory','256m','--memory-swap','256m','--pids-limit','32','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only',metadata['Id'],'python','-I','-c',code]
    checked=subprocess.run(command,capture_output=True,text=True,check=True)
    observed=json.loads(checked.stdout)
    expected=tree_hashes(root/'tasks'/task/'environment/public-dev')
    checks={'nonroot':observed['uid']==1000,'input_exact_match':expected==observed['files'],'six_cases':len(json.loads((root/'tasks'/task/'environment/public-dev/manifest.json').read_text())['cases'])==6,'zero_capabilities':'CapEff:\t0000000000000000' in observed['status'],'no_new_privileges':'NoNewPrivs:\t1' in observed['status'],'protected_helpers':not observed['helpers_writable'],'protected_responses':not observed['responses_writable'],'no_socket':not observed['socket_present']}
    rows.append({'task':task,'image_id':metadata['Id'],'image_inspect':metadata,'context_hashes':tree_hashes(root/'tasks'/task/'environment'),'command':command,'observed':observed,'checks':checks,'passed':all(checks.values())})
write_json(root/'logs/research-images-local-001/result.json',{'formal':False,'scope':'local immutable image boot and public input inspection','rows':rows,'passed':all(r['passed'] for r in rows)})
print(json.dumps([{'task':r['task'],'image':r['image_id'],'checks':r['checks']} for r in rows]))
assert all(r['passed'] for r in rows)
