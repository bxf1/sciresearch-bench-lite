"""Diagnostic physics and phase isolation, using disposable cases only."""
import copy
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from authoring import heat, ode
from authoring.diagnostics import specifications
from runner.common import VERSION, write_json
from runner.phase import PhaseError, validate_manifest, guard_replay
from judge import heat as heat_judge
from runner.model_relay import Relay, Limits


@pytest.mark.parametrize("profile", ["main", "coordinate_scale", "coordinate_swap", "stable_cubic"])
def test_ode_analytic_field_and_lyapunov_identity(profile):
    parameters = np.array([.9, .25, .4, .2]) if profile != "stable_cubic" else np.array([.3, .4, .5, .6, .2, 1.2])
    coefficients, rhs, energy, identity = ode.diagnostic_system(parameters, profile)
    states = np.random.default_rng(48).normal(size=(100, 2))
    np.testing.assert_allclose(ode.polynomial_library(states) @ coefficients, rhs(states), rtol=1e-13, atol=1e-13)
    assert np.count_nonzero(coefficients) <= 10
    velocity = rhs(states)
    finite_difference = (energy(states + 1e-6*velocity) - energy(states - 1e-6*velocity))/2e-6
    chain, analytic = identity(states, velocity)
    np.testing.assert_allclose(chain, analytic, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(finite_difference, analytic, rtol=1e-6, atol=1e-6)
    assert (analytic <= 0).all()


@pytest.mark.parametrize("amplitude", [.5, 2.])
def test_heat_diagnostic_truth_does_not_relax_main_norm_check(tmp_path, amplitude):
    public, private = tmp_path/'input', tmp_path/'private'
    public.mkdir(); private.mkdir()
    rngs = {key: np.random.default_rng(i+90) for i, key in enumerate(('system','mask','noise','solution'))}
    heat.generate_case(public, private, 2, rngs, diagnostic={'amplitude':amplitude, 'contiguous_mask':True})
    mask = np.load(private/'mask.npy')
    for row in mask:
        missing = np.flatnonzero(~row)
        assert len(missing) == 32 and np.array_equal(missing, np.arange(missing[0], missing[0]+32))
    truth = private/'u0_true.npy'
    assert heat_judge.score_case(public, private, truth, expected_amplitude=amplitude)['scientific_pass']
    with pytest.raises(heat_judge.EvaluationInvalid):
        heat_judge.score_case(public, private, truth)


def test_diagnostic_manifest_is_distinct_from_main_and_locked(tmp_path):
    rows=[]
    for i, row in enumerate(specifications('heat')):
        path=f'cases/case-{i}'
        (tmp_path/path).mkdir(parents=True)
        rows.append({'id':f'case-{i}','path':path,**{k:row[k] for k in ('level','profile_id','profile_index')}})
    manifest={'task':'heat','contract_version':VERSION,'split':'diagnostic-test',
              'purpose':'diagnostic_only_excluded_from_main_score','cases':rows}
    write_json(tmp_path/'manifest.json',manifest)
    assert len(validate_manifest('heat',tmp_path)['cases'])==12
    with pytest.raises(PhaseError):
        guard_replay('heat',tmp_path,tmp_path,None,None)
    manifest['split']='final-test'
    write_json(tmp_path/'manifest.json',manifest)
    with pytest.raises(PhaseError):
        validate_manifest('heat',tmp_path)


def test_host_reminders_skip_compaction_coalesce_and_keep_tool_results(tmp_path):
    budget=tmp_path/'budget.json'
    write_json(budget,{'started_at':1000.,'deadline':2800.,'thresholds_seconds':[600,300,120]})
    relay=Relay('provider-secret', 's'*32, tmp_path/'events.jsonl', Limits(), budget_path=budget)
    original={'messages':[{'role':'user','content':[{'type':'tool_result','tool_use_id':'a','content':'ok'}]}], 'tools':[]}
    try:
        value=copy.deepcopy(original)
        with patch('runner.model_relay.time.time',return_value=2300.): relay.remind(value)
        assert value['messages'][0]['content'][0] == original['messages'][0]['content'][0]
        assert '500 seconds' in value['messages'][0]['content'][1]['text']
        value=copy.deepcopy(original)
        with patch('runner.model_relay.time.time',return_value=2400.): relay.remind(value)
        assert value == original
        compaction={'messages':copy.deepcopy(original['messages'])}
        with patch('runner.model_relay.time.time',return_value=2700.): relay.remind(compaction)
        assert relay.budget_sent == {600}
        with patch('runner.model_relay.time.time',return_value=2700.): relay.remind(value)
        assert relay.budget_sent == {600,300,120}
        assert len(value['messages'][0]['content'])==2
    finally:
        relay.events.close()
