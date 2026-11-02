"""Contract boundary tests inject exact metrics; physics/GT checks are tested separately."""
from unittest.mock import patch
import numpy as np
import pytest
from judge import heat, ode, poisson


@pytest.mark.parametrize('metric,limit', [('initial',.15),('future',.03)])
@pytest.mark.parametrize('side,expected',[(-1,True),(0,True),(1,False)])
def test_heat_inclusive_thresholds(tmp_path,metric,limit,side,expected):
    value=limit if side==0 else np.nextafter(limit,0 if side<0 else np.inf)
    artifact=tmp_path/'u0.npy';np.save(artifact,np.ones(256))
    truth=({'kappa':1.,'future_time':.01},np.arange(1,257)/257,np.ones(256),np.ones(256))
    errors=[value,0.] if metric=='initial' else [0.,value]
    with patch.object(heat,'_truth',return_value=truth),patch.object(heat,'_relative',side_effect=errors):
        assert heat.score_case(tmp_path,tmp_path,artifact)['scientific_pass']==expected


@pytest.mark.parametrize('metric',['field','rollout'])
@pytest.mark.parametrize('side,expected',[(-1,True),(0,True),(1,False)])
def test_ode_inclusive_thresholds(tmp_path,metric,side,expected):
    value=.05 if side==0 else np.nextafter(.05,0 if side<0 else np.inf)
    truth={'field_grid':np.zeros((441,2)),'field_true':np.ones((441,2)),
           'hidden_initial':np.zeros((4,2)),'hidden_clean':np.ones((4,401,2)),'hidden_t':np.linspace(0,8,401)}
    errors=[value,0.,0.,0.,0.] if metric=='field' else [0.,value,value,value,value]
    with patch.object(ode,'_ground_truth',return_value=truth),patch.object(ode,'load_model',return_value=np.zeros((10,2))),\
         patch.object(ode,'bounded_rollout',return_value={'status':'success','values':np.ones((401,2))}),\
         patch.object(ode,'relative_error',side_effect=errors):
        assert ode.score_case(tmp_path,tmp_path,tmp_path/'model.json')['scientific_pass']==expected


@pytest.mark.parametrize('metric,limit',[('residual',1e-8),('solution',1e-5)])
@pytest.mark.parametrize('side,expected',[(-1,True),(0,True),(1,False)])
def test_poisson_inclusive_thresholds(tmp_path,metric,limit,side,expected):
    value=limit if side==0 else np.nextafter(limit,0 if side<0 else np.inf)
    error=value if metric=='solution' else 0.
    residual=[value]*4 if metric=='residual' else [0.]*4
    with patch.object(poisson,'_trusted_inputs',return_value=(None,np.ones((1,4)),np.ones((1,4)))),\
         patch.object(poisson,'load_solution',return_value=np.ones((1,4))),\
         patch.object(poisson,'residual_errors',return_value=residual),\
         patch.object(poisson.np.linalg,'norm',side_effect=[error,1.]*4):
        assert poisson.score_case(tmp_path,tmp_path,tmp_path/'solution.npy')['scientific_pass']==expected
