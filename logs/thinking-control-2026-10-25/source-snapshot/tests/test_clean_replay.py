from pathlib import Path
import pytest

from runner.clean_replay import registered_source
from runner.common import read_json, write_json
from runner.registry import Registry


def candidate(tmp_path, status=None):
    workspace=tmp_path/'workspace'
    source=workspace/'candidate'
    source.mkdir(parents=True)
    (source/'solve.py').write_text('pass\n')
    registry=Registry.create(tmp_path/'registry',workspace,'heat','g1-pilot')
    registry.evaluate('candidate',lambda *args:{'artifact_valid':True})
    registry.close(attempt_status=status)
    return registry


@pytest.mark.parametrize('status',[None,'completed','research_timeout'])
def test_allows_legacy_and_valid_trusted_outcomes(tmp_path,status):
    registry=candidate(tmp_path,status)
    source,sha=registered_source(registry)
    assert (source/'solve.py').read_text()=='pass\n'
    assert sha==read_json(registry.root/'state.json')['evaluations'][0]['source_hash']


@pytest.mark.parametrize('status',['api_failed','infrastructure_failed','cancelled'])
def test_rejects_invalid_trusted_research_outcomes(tmp_path,status):
    registry=candidate(tmp_path,status)
    with pytest.raises(ValueError,match='failed research attempt'):
        registered_source(registry)


@pytest.mark.parametrize('change',[{'source_hash':'0'*64},{'artifact_valid':False},{'completed_at':None}])
def test_matches_final_snapshot_to_completed_valid_registration(tmp_path,change):
    registry=candidate(tmp_path)
    state=read_json(registry.root/'state.json')
    state['evaluations'][0].update(change)
    write_json(registry.root/'state.json',state)
    with pytest.raises(ValueError):
        registered_source(registry)
