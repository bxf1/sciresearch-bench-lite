"""Offline author acceptance on calibration data; never evaluates final-test."""
import importlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runner.common import read_json, write_json, tree_hashes, file_hash
from runner.calibrate import calibrate, FIXED
from runner.replay import prepare_judge, replay_single

OUT=ROOT/'logs/optimized-r1-20261101'
DATA=ROOT/'authoring/data/optimized-r1-20261101'


def audit():
    generation=read_json(DATA/'private/generation.json')
    assert generation['cases']==162 and generation['status']=='generated_qc_passed_not_frozen'
    assert tree_hashes(DATA/'inputs')==read_json(DATA/'private/input_manifest.json')
    qc=[]
    for path in (DATA/'private').glob('*/cases/*/manifest.json'):
        raise AssertionError('unexpected shallow case path')
    for path in (DATA/'private').glob('*/*/cases/*/manifest.json'):
        row=read_json(path)
        actual=tree_hashes(path.parent);actual.pop('manifest.json')
        assert actual==row['private_hashes'],path
        assert row['evidence']['qc']['passed']
        qc.append({'id':row['id'],'namespace':row['namespace'],'passed':True})
    assert len(qc)==162
    write_json(OUT/'gt-qc.json',{'status':'passed','cases':qc,'count':162,'input_manifest_sha256':file_hash(DATA/'private/input_manifest.json')})
    results=[]
    for task in ('heat','ode','poisson'):
        scorer=importlib.import_module('judge.'+task)
        for split in ('author-calibration','diagnostic-calibration'):
            inputs=DATA/'inputs'/task/split;truth=DATA/'private'/task/split
            for entry in read_json(inputs/'manifest.json')['cases']:
                private=truth/entry['path'];public=inputs/entry['path']
                artifacts=OUT/'rule-fixtures'/task/split/entry['id'];artifacts.mkdir(parents=True)
                options={}
                if task=='heat':
                    expected=np.load(private/'u0_true.npy');name='u0.npy'
                    if entry.get('profile_id')=='amplitude':options['expected_amplitude']=(.5,2.)[entry['profile_index']//2]
                elif task=='ode':
                    expected=np.load(private/'coefficients.npy');name='model.json'
                else:
                    with np.load(private/'truth.npz') as archive:expected=archive['solution']
                    name='solution.npy'
                values={}
                for kind, data in (('oracle',expected),('zero',np.zeros_like(expected))):
                    directory=artifacts/kind;directory.mkdir()
                    path=directory/name
                    if task=='ode':write_json(path,{'coefficients':data.tolist()})
                    else:np.save(path,data,allow_pickle=False)
                    value=scorer.score_case(public,private,path,**options)
                    assert value['evaluation_status']=='valid' and value['artifact_valid']
                    assert value['scientific_pass'] == (kind=='oracle'),(task,entry,kind,value)
                    values[kind]=value
                results.append({'task':task,'split':split,'id':entry['id'],'checks':values})
    write_json(OUT/'rule-fixtures.json',{'status':'passed','cases':72,'results':results,'oracle_is_rule_check_not_algorithm_result':True})


def main():
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(143))
    audit()
    name='dcomp-demo-postgres'
    before=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',name],text=True))
    running=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
    assert set(running).issubset({name})
    restoration={'container':name,'before_running':before['Running'],'restored':False,'started_at':time.time()}
    write_json(OUT/'calibration-service-restoration.json',restoration)
    try:
        if before['Running']:subprocess.run(['docker','stop',name],check=True,stdout=subprocess.DEVNULL)
        with (OUT/'resource-acceptance.stdout.log').open('x') as stream:
            subprocess.run([sys.executable,'tests/resource_acceptance_probe.py','--output',str(OUT/'resource-acceptance'),
                            '--plan',str(OUT/'research-images.json')],cwd=ROOT,check=True,stdout=stream,stderr=subprocess.STDOUT,
                            env={**__import__('os').environ,'PYTHONPATH':str(ROOT)})
        image=read_json(OUT/'resource-acceptance/summary.json')['numeric_image_id']
        main_result=calibrate(ROOT,DATA,OUT/'main-calibration',image)
        assert all(r['result']['evaluation_status']=='valid' for r in main_result['methods'])
        judge=prepare_judge(ROOT,OUT/'diagnostic-calibration/judge-source')
        inventory=read_json(DATA/'diagnostic-views/inventory.json')
        rows=[]
        for task in ('heat','ode','poisson'):
            keys=(['diagnostic-calibration/all/forward'] if task!='poisson' else
                  ['diagnostic-calibration/'+p+'/forward' for p in ('large_grid','five_disks','cache_order')])
            for key in keys:
                view=inventory[task][key]
                result=replay_single(ROOT/'baselines'/task,task=task,input_root=Path(view['input']),truth_root=Path(view['truth']),
                                     output_root=OUT/'diagnostic-calibration'/task/key.replace('/','-'),
                                     image=image,judge_source_root=judge,method=FIXED[task])
                rows.append({'task':task,'profile':key,'method':FIXED[task],'result':result})
                write_json(OUT/'diagnostic-calibration/summary.json',{'status':'running','rows':rows})
                assert result['evaluation_status']=='valid' and result['artifact_valid'],(task,key,result.get('attempt_status'))
        write_json(OUT/'diagnostic-calibration/summary.json',{'status':'passed','rows':rows,
                   'acceptance':'Reference algorithms must execute legal artifacts within resources; diagnostic accuracy is measured, not used to replace cases.'})
        write_json(OUT/'offline-acceptance.json',{'status':'passed','gt_qc':file_hash(OUT/'gt-qc.json'),
                   'rule_fixtures':file_hash(OUT/'rule-fixtures.json'),'resources':file_hash(OUT/'resource-acceptance/summary.json'),
                   'main_calibration':file_hash(OUT/'main-calibration/summary.json'),
                   'diagnostic_calibration':file_hash(OUT/'diagnostic-calibration/summary.json'),
                   'model_calls':0,'test_scores_accessed':False})
        print('Offline acceptance passed',flush=True)
    finally:
        if before['Running']:
            subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL)
        after=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',name],text=True))
        restoration.update(after_running=after['Running'],restored=after['Running']==before['Running'],finished_at=time.time())
        write_json(OUT/'calibration-service-restoration.json',restoration)
        assert restoration['restored']


if __name__=='__main__':main()
