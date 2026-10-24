"""Verifier cleanup must be proven by host metadata, not native stop's return."""
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from runner.verify_pilot import cleanup_environment,record_cleanup


class VerifyPilotCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def check(self,outputs,stop_error=None):
        environment=SimpleNamespace(stop=AsyncMock(side_effect=stop_error))
        calls=[]
        def docker(*args,**kwargs):
            calls.append((args,kwargs))
            value=outputs[len(calls)-1]
            if isinstance(value,Exception):
                raise value
            return SimpleNamespace(returncode=0,stdout=value,stderr='')
        with patch('runner.verify_pilot.docker',side_effect=docker):
            evidence=await cleanup_environment(environment,'bench-verify-pilot-test')
        environment.stop.assert_awaited_once_with(delete=True)
        return evidence,calls

    async def test_success_requires_all_three_exact_session_inspections(self):
        evidence,calls=await self.check(['','',''])
        self.assertTrue(evidence['orchestration_environment_removed'])
        self.assertEqual(evidence['cleanup_errors'],{})
        self.assertEqual([call[0][:-2] for call in calls],[('ps','-aq'),('network','ls','-q'),('volume','ls','-q')])
        for args,kwargs in calls:
            self.assertEqual(args[-2:],('--filter','label=com.docker.compose.project=bench-verify-pilot-test'))
            self.assertEqual(kwargs,{'timeout':30,'check':False})

    async def test_native_swallowed_cleanup_error_cannot_hide_residual_resources(self):
        evidence,_=await self.check(['remaining-container\n','remaining-network\n','remaining-volume\n'])
        self.assertTrue(evidence['native_stop_returned'])
        self.assertFalse(evidence['orchestration_environment_removed'])
        self.assertEqual(set(evidence['cleanup_errors']),{'containers','networks','volumes'})
        result={'status':'pilot_verifier_completed','score':100,'reward':1}
        record_cleanup(result,evidence)
        self.assertEqual(result['status'],'pilot_evaluation_invalid')
        self.assertEqual(result['pre_cleanup_status'],'pilot_verifier_completed')
        self.assertIsNone(result['score'])
        self.assertIsNone(result['reward'])
        self.assertEqual(result['cleanup_evidence']['remaining_own_containers'],['remaining-container'])

    async def test_stop_exception_does_not_skip_any_inspection(self):
        evidence,calls=await self.check(['','',''],RuntimeError('synthetic native down failure'))
        self.assertEqual(len(calls),3)
        self.assertFalse(evidence['native_stop_returned'])
        self.assertTrue(evidence['orchestration_environment_removed'])
        self.assertIn('native_stop',evidence['cleanup_errors'])
        result={'status':'pilot_verifier_completed','score':100,'reward':1}
        record_cleanup(result,evidence)
        self.assertEqual(result['status'],'pilot_evaluation_invalid')

    async def test_docker_timeout_is_unknown_not_success_and_other_checks_continue(self):
        evidence,calls=await self.check([subprocess.TimeoutExpired('docker ps',30),'',''])
        self.assertEqual(len(calls),3)
        self.assertFalse(evidence['orchestration_environment_removed'])
        self.assertEqual(evidence['remaining_own_containers'],['inspection_failed'])
        self.assertIn('TimeoutExpired',evidence['cleanup_errors']['containers'])

    async def test_nonzero_inspection_is_not_treated_as_empty(self):
        environment=SimpleNamespace(stop=AsyncMock())
        with patch('runner.verify_pilot.docker',return_value=SimpleNamespace(returncode=1,stdout='',stderr='synthetic daemon unavailable')):
            evidence=await cleanup_environment(environment,'bench-verify-pilot-test')
        self.assertFalse(evidence['orchestration_environment_removed'])
        self.assertEqual(set(evidence['cleanup_errors']),{'containers','networks','volumes'})


if __name__=='__main__':
    unittest.main()
