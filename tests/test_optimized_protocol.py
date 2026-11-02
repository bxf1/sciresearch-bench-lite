"""Predeclared research barrier, observed timing selection, and timeline accounting."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runner import study, observed
from runner.common import write_json
from runner.exploration import attempt_timeline
from runner.file_bridge import DockerFileTransport
from runner.phase import RESOURCES


def test_global_barrier_includes_other_tasks():
    plan={'runs':[{'run_id':t,'task':t} for t in ('heat','ode','poisson')],
          'execution_policy':{'global_research_closure_before_hidden_scoring':True}}
    manifest={'attempts':[{'run_id':'heat'},{'run_id':'ode'}]}
    with patch.object(study,'closed_research') as check,patch.object(study,'read_attempt',return_value={'attempt_status':'completed'}):
        with pytest.raises(ValueError,match='all related research'):
            study.completed_task(Path('.'),plan,manifest,'heat')
        assert [c.args[1]['run_id'] for c in check.call_args_list]==['heat','ode']


def test_workspace_root_rejected_before_export_process():
    with patch('runner.file_bridge.subprocess.Popen') as popen:
        with pytest.raises(ValueError):
            DockerFileTransport('test-container').export_source('.',Path('/unused'),10)
        popen.assert_not_called()


class FakeObserver:
    def __init__(self,path):
        self.path=path;path.write_text('synthetic observation\n')
        import threading
        self.stop=threading.Event();self.errors=[]
    def sample(self):pass
    def watch(self):pass
    def violations_since(self,start):return []


@pytest.mark.parametrize('statuses,expected_calls',[
    (['baseline_unstable','valid','valid'],2),
    (['candidate_failed','valid'],1),
    (['invalid_environment']*3,3),
])
def test_first_valid_timing_and_three_attempt_bound(tmp_path,statuses,expected_calls):
    resource=tmp_path/'resources.json'
    write_json(resource,{'formal_resources_accepted':True,'resources':RESOURCES,'numeric_image_id':'test','machine_id':'test'})
    calls=[]
    def execute(*args,**kwargs):
        status=statuses[len(calls)];calls.append(kwargs)
        return {'performance_status':status,'evaluation_status':'evaluation_invalid' if status=='invalid_environment' else 'valid',
                'score':0 if status=='candidate_failed' else (51 if status=='valid' else None),
                'reward':0 if status=='candidate_failed' else (1 if status=='valid' else None),'speedup':3.0 if status=='valid' else None}
    with patch.object(observed,'Observer',FakeObserver),patch.object(observed,'docker',return_value=SimpleNamespace(stdout='')),\
         patch.object(observed.time,'sleep'),patch.object(observed,'run_t3_attempt',side_effect=execute):
        value=observed.observed_bccbbc(tmp_path,resource_path=resource,baseline_source=tmp_path,output_root=tmp_path/'result')
    assert len(calls)==expected_calls
    assert len(value['timing_attempts'])==expected_calls
    if statuses[-1]=='invalid_environment':
        assert value['score'] is None and value['selected_window'] is None
    else:
        assert value['selected_window']==expected_calls
        assert value['score']==(0 if statuses[0]=='candidate_failed' else 51)


def test_timeline_counts_unique_sources_and_does_not_invent_durations(tmp_path):
    state={'started_at':100,'evaluations':[{'id':'candidate-001','source_hash':'a','artifact_valid':True,'accepted_at':110},
                                          {'id':'candidate-002','source_hash':'a','artifact_valid':True,'accepted_at':120}],
           'first_id':'candidate-001','final_id':'candidate-002','selection_reason':'deadline_fallback'}
    write_json(tmp_path/'registry/state.json',state)
    row=attempt_timeline(tmp_path)
    assert row['summary']['accepted_public_evaluations']==2
    assert row['summary']['unique_valid_source_hashes']==1
    assert row['summary']['first_valid_registration_seconds']==10
    assert row['tools']==[]
