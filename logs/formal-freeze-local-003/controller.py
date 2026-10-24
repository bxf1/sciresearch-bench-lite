"""User-authorized cumulative-output budget revision; preserves previous freezes."""
import copy
import datetime
import json
import shutil
import subprocess
from pathlib import Path
from runner import phase, run_plan
from runner.common import canonical, digest, file_hash, read_json, write_json
from runner.model_relay import Limits
from runner.study import session_spec

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT/'freezes/research-run-plan-formal-002.json'
NEW = ROOT/'freezes/research-run-plan-formal-003.json'

def ref(path):
    path = Path(path)
    if not path.is_absolute(): path = ROOT/path
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':file_hash(path)}

def evidence(name, value):
    path = OUT/(name+'.json')
    assert not path.exists(), path
    write_json(path, value)
    return ref(path)

def main():
    assert not NEW.exists()
    assert file_hash(PRIOR) == '5ab5c8e35ce5afa39ebfd53482dfa49d86f7401e76e7ce0af0d579dbfad4cceb'
    old = read_json(PRIOR)
    ledger = ROOT/'research-runs'/old['plan_id']/'manifest.json'
    stopped = read_json(OUT/'predecessor-closed.json')
    assert stopped['status']=='closed_for_budget_revision' and stopped['ledger']==ref(ledger)
    assert not read_json(ledger)['finalized_tasks']
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    authorization = ref(OUT/'authorization.json')
    draft = run_plan.create_draft(ROOT, order_entropy=old['order']['entropy_hex'], identity_revision='budget-200k-001')
    assert draft['tasks']==old['tasks'] and draft['resources']==old['resources']
    plan = copy.deepcopy(old)
    for key in ('plan_id','runs','run_matrix_sha256','created_at','identity_revision'):
        plan[key] = draft[key]
    plan.update(previous_plan=ref(PRIOR), revision_authorization=authorization,
                previous_attempts=ref(ledger), predecessor_close=ref(OUT/'predecessor-closed.json'))
    plan.pop('previous_failed_attempts', None)
    plan['tool_config']['files'] = draft['tool_config']['files']
    plan['tool_config_sha256'] = digest(canonical(plan['tool_config']))
    changed = {name:{'old_sha256':sha,'new_sha256':file_hash(ROOT/name)}
               for name,sha in old['tool_config']['files'].items() if file_hash(ROOT/name)!=sha}
    assert set(changed)=={'runner/model_relay.py','runner/relay_transport.py','runner/study.py','runner/harbor_pilot.py'}
    numeric = read_json(ROOT/'logs/formal-freeze-local-001/model-switch-impact.json')['numerical_sources_unchanged']
    assert not set(changed).intersection(numeric)
    assert all(file_hash(ROOT/name)==old['tool_config']['files'][name] for name in numeric)
    impact = evidence('revision-impact', {'status':'passed','changed_trusted_files':changed,
        'numerical_sources_unchanged':numeric,
        'budget_change':{'session_output_tokens':{'old':32768,'new':200000},'max_requests':{'old':512,'new':3125}},
        'diagnostic_change':'Rejected decreasing usage retains only its field name and validated integer previous/observed values; acceptance and accounting rules unchanged.',
        'unchanged':{'request_output_limit':4096,'research_seconds':1800,'accepted_evaluations':20,
            'model_prompts_tools_data_images_resources_scoring_order':True,'native_context_window':128000,'native_max_tokens':16384},
        'prior_attempts':'Retained as predecessor-version evidence, excluded from new-version 15-session denominator.',
        'fresh_observed_t3_window_required':True})
    policy = read_json(ROOT/old['tool_config']['runtime_enforcement']['path'])
    live = read_json(OUT/'live-smoke-result.json')
    summary = read_json(OUT/'native-live-summary/result.json')
    assert live['status']==summary['status']=='passed' and summary['cleanup']['all_removed']
    assert summary['relay_status']['limits']['session_output_limit']==200000
    assert summary['relay_status']['limits']['max_requests']==3125
    log = OUT/'unit-tests-final.txt'
    assert '357 passed' in log.read_text()
    enforcement = evidence('model-enforcement', {'status':'verified','model_id':old['model']['model_id'],
        'model_version':old['model']['model_version'],'thinking':old['model']['thinking'],
        'temperature':old['model']['temperature'],'top_p':old['model']['top_p'],
        'request_output_limit':4096,'session_output_limit':200000,'max_requests':3125,
        'provider_version':old['model']['version_resolution']['evidence'],
        'native_live':ref(OUT/'native-live-summary/result.json'),
        'prior_native_pilot':ref('logs/harbor-native-compaction-pilot-001/result.json'),
        'unit_tests':ref(log),'boundary_coverage':'49 successful synthetic streams charge exactly 200000 (48*4096+3392), then reject; 513 one-token requests remain admitted.',
        'runtime_policy_unchanged':old['tool_config']['runtime_enforcement'],
        'scope':'Rebind new limits and parameter plumbing. Scientific kernels and native Pi payload/source policy unchanged. No hidden scores.'})
    plan['model']['output_token_limit'] = 200000
    plan['model']['enforcement'] = {k:{'status':'verified','evidence':enforcement} for k in run_plan.PARAMETERS}
    plan['runtime_policy'] = Limits(session_seconds=2700, session_output_limit=200000, max_requests=3125,
        expected_system_sha256=policy['wire_system_sha256'], expected_tools_sha256=policy['wire_tools_sha256'],
        expected_compaction_system_sha256=policy['native_compaction']['wire_system_sha256']).public()
    scorer = evidence('scorer-tests', {'status':'passed','unit_tests_passed':357,'unit_test_log':ref(log),
        'trusted_source_hashes':plan['tool_config']['files'],
        'test_source_hashes':{p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted((ROOT/'tests').glob('test_*.py'))}})
    info = json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],text=True))
    machine = subprocess.check_output(['colima','ssh','--','cat','/proc/sys/kernel/random/boot_id'],text=True).strip()
    resource = read_json(ROOT/'logs/resource-acceptance-local-002/summary.json')
    assert machine==resource['machine_id'] and info['NCPU']>=6 and info['MemTotal']>=8.5*1024**3
    assert not subprocess.check_output(['docker','ps','-q'],text=True).strip()
    for image in [resource['numeric_image_id'],*[r['image_id'] for r in old['research_images'].values()]]:
        assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',image],text=True).strip()==image
    environment = evidence('environment-inspection', {'status':'verified','observed_at_utc':now,'vm_boot_id':machine,
        'docker':{k:info[k] for k in ('NCPU','MemTotal','CgroupVersion','KernelVersion','Architecture','OperatingSystem')},
        'running_containers':[],'power':subprocess.check_output(['pmset','-g','batt'],text=True),
        'scope':'Startup resource and VM/image identity; fresh continuous T3 qualification still required.'})
    resources = evidence('resources', {'status':'passed','formal_resources_accepted':True,'resources':phase.RESOURCES,
        'prior_acceptance':ref('freezes/resource-acceptance-local-001.json'),'current_environment':environment,'revision_impact':impact})
    for task in phase.TASKS:
        prior = read_json(ROOT/old['freezes'][task]['path'])
        frozen = copy.deepcopy(prior)
        frozen.update(frozen_at=now, previous_freeze=old['freezes'][task], revision_authorization=authorization)
        checks = copy.deepcopy(plan['acceptance_evidence'][task])
        checks.update(scorer_tests=scorer, resources=resources)
        checks['model_smoke'] = evidence(task+'-model-smoke', {'status':'passed','model_id':plan['model']['model_id'],
            'new_budget_native_live':ref(OUT/'native-live-summary/result.json'),
            'prior_task_policy':ref('logs/model-policy-capture-compaction-local-003/'+task+'/policy.json'),
            'prior_harbor_pilot':ref('logs/harbor-native-compaction-pilot-001/result.json'),'revision_impact':impact})
        frozen['acceptance'] = {key:{'status':'passed','evidence_sha256':value['sha256']} for key,value in checks.items()}
        frozen['research'].update(output_token_limit=200000, tool_config_sha256=plan['tool_config_sha256'],
            run_matrix_sha256=plan['run_matrix_sha256'], model_parameter_enforcement=plan['model']['enforcement'])
        frozen['limitations'] = ['User-authorized 200000 cumulative output budget revision; predecessor evidence retained.',
            'Provider alias mapping retained. All 15 new research sessions close before hidden scoring.',
            'Fresh continuous host observation required for T3.']
        for key in ('data','data_sha256','thresholds','resources','dependencies','profile','image_id','judge_source_hashes','judge_sha256'):
            assert frozen[key]==prior[key]
        phase.validate_freeze_document(frozen, task)
        path = ROOT/f'freezes/{task}-formal-003.json'
        assert not path.exists()
        write_json(path, frozen)
        plan['freezes'][task] = ref(path)
        plan['acceptance_evidence'][task] = checks
    plan.update(frozen_at=now, revision_impact=impact)
    plan['limitations'] = ['200000 cumulative output tokens per session, 4096 per request, 3125 requests; original 1800 seconds/20 evaluations retained.',
        'Fresh independent identities; same model, research prompts, data, images, scoring, resources and order.',
        'Versions 001/002 and all prior costs/failures retained separately; no prior hidden test scores accessed.',
        'Provider alias is not immutable backend identity. T3 needs fresh continuous observation.']
    run_plan.validate_start(plan, ROOT)
    write_json(NEW, plan)
    for row in plan['runs']:
        settings = session_spec(ROOT, NEW, row['run_id'], row['run_id']+'-a001')['settings']
        assert settings['session_output_limit']==200000 and settings['request_output_limit']==4096 and settings['max_requests']==3125
        assert settings['expected_compaction_sources']==policy['native_compaction']['source_sha256']
    paths = set(plan['tool_config']['files'])|{p.relative_to(ROOT).as_posix() for p in (ROOT/'tests').glob('*.py')}
    paths |= {p.relative_to(ROOT).as_posix() for folder in ('prompts','tasks') for p in (ROOT/folder).rglob('*') if p.is_file()}
    snapshot = {}
    for name in sorted(paths):
        target = OUT/'source-snapshot'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
        snapshot[name] = file_hash(target)
    evidence('source-snapshot-manifest', {'files':snapshot})
    evidence('validation', {'status':'passed','formal_ready':True,'blockers':[],'plan':ref(NEW),
        'previous_plan':ref(PRIOR),'all_15_specs_validated':True,'predecessor_ledger_unchanged':ref(ledger),
        'formal_sessions_started':0,'final_test_scores_accessed':False})
    print(json.dumps({'status':'frozen','plan_id':plan['plan_id'],'plan':ref(NEW),'sessions':15}))

if __name__=='__main__': main()
