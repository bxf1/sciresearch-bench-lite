"""Unit checks for pilot admission and bounded/redacted auxiliary retention."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from runner.research_loop import BoundedReader, public_input, retain_logs


class Process:
    def __init__(self, payload):
        self.stdout, self.stderr = io.BytesIO(payload), io.BytesIO()
    def kill(self):
        pass
    def poll(self):
        return 0
    def wait(self, timeout=None):
        return 0


def archive(files, symlink=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as tar:
        for name, payload in files:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            if symlink:
                info.type, info.linkname, info.size = tarfile.SYMTYPE, '/etc/passwd', 0
            tar.addfile(info, None if symlink else io.BytesIO(payload))
    return stream.getvalue()


class ResearchLoopTests(unittest.TestCase):
    def test_auxiliary_secret_redaction_before_retention(self):
        payload = archive([('./pi.txt', b'hello top-secret'), ('pi/sessions/a.jsonl', b'{"x":"top-secret"}')])
        with tempfile.TemporaryDirectory() as directory, patch('runner.research_loop.subprocess.Popen', return_value=Process(payload)):
            result = retain_logs('container', Path(directory), 'top-secret')
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['files']), 2)
            self.assertNotIn(b'top-secret', (Path(directory)/'pi.txt').read_bytes())

    def test_auxiliary_links_and_traversal_rejected(self):
        for payload in (archive([('pi.txt', b'')], symlink=True), archive([('../pi.txt', b'no')])):
            with tempfile.TemporaryDirectory() as directory, patch('runner.research_loop.subprocess.Popen', return_value=Process(payload)):
                with self.assertRaises(ValueError):
                    retain_logs('container', Path(directory), 'top-secret')

    def test_auxiliary_quota(self):
        payload = archive([('pi.txt', b'abcd')])
        with tempfile.TemporaryDirectory() as directory, patch('runner.research_loop.subprocess.Popen', return_value=Process(payload)), patch('runner.research_loop.MAX_LOG_FILE', 3):
            with self.assertRaisesRegex(ValueError, 'quota'):
                retain_logs('container', Path(directory), 'top-secret')
        with self.assertRaisesRegex(ValueError, 'quota'):
            BoundedReader(io.BytesIO(b'abcd'), 3).read(4)

    def test_public_only_manifest_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'manifest.json').write_text(json.dumps({'task':'heat','contract_version':'0.3.0','split':'final-test','cases':[]}))
            with self.assertRaisesRegex(ValueError, 'split'):
                public_input(root)


class AuxiliaryDecodeTests(unittest.TestCase):
    def test_unicode_and_base64_are_redacted_and_images_omitted(self):
        import base64
        from runner.research_loop import sanitize_log_bytes
        secret='model-secret-value'
        escaped=''.join('\\u%04x'%ord(x) for x in secret)
        payload=json.dumps({'text':escaped,'encoded':base64.b64encode(secret.encode()).decode(),
            'content':[{'type':'image','data':base64.b64encode(secret.encode()).decode()}]}).encode()
        cleaned=sanitize_log_bytes(payload,secret)
        parsed=json.loads(cleaned)
        self.assertNotIn(secret,json.dumps(parsed))
        self.assertEqual(parsed['content'][0]['type'],'omitted_attachment')
        self.assertNotIn('data',parsed['content'][0])
        self.assertIn('REDACTED',parsed['encoded'])

    def test_usage_is_read_only_auxiliary_and_no_attachments_written(self):
        from runner.research_loop import auxiliary_usage
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'pi/sessions';p.mkdir(parents=True)
            row={'type':'message','message':{'role':'assistant','model':'test-model','usage':{'input':5,'output':3,'cacheRead':7,'totalTokens':15},'content':[{'type':'thinking','thinking':'test'}]}}
            (p/'a.jsonl').write_text(json.dumps(row)+'\n')
            before={str(x) for x in Path(directory).rglob('*')}
            result=auxiliary_usage(Path(directory))
            self.assertEqual(result['reported_n_input_tokens_including_cache'],12)
            self.assertEqual(result['observed_thinking_blocks'],1)
            self.assertIsNone(result['cost_usd'])
            self.assertEqual(before,{str(x) for x in Path(directory).rglob('*')})


class CleanupTests(unittest.TestCase):
    def test_worker_cleanup_is_scoped_to_this_run_records(self):
        from types import SimpleNamespace
        from runner.research_loop import cleanup_own_workers
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'this-run/evaluations'; own=root/'candidate-001'; own.mkdir(parents=True)
            other=Path(directory)/'other-run/evaluations/candidate-001'; other.mkdir(parents=True)
            name='sciresearch-w-'+'1'*12; identity='a'*64
            (own/'worker.json').write_text(json.dumps({'container_name':name}))
            (other/'worker.json').write_text(json.dumps({'container_name':'sciresearch-w-'+'2'*12}))
            calls=[]
            def cmd(argv,**kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=0,stdout=identity+'\n' if len(calls)==1 else '')
            with patch('runner.research_loop.command',side_effect=cmd):
                result=cleanup_own_workers(root)
            self.assertTrue(result['all_removed'])
            expected=['docker','ps','-aq','--no-trunc','--filter','name=^/'+name+'$']
            self.assertEqual(calls,[expected,['docker','rm','-f',identity],expected])
            self.assertEqual(len(result['records']),1)

    def test_worker_cleanup_falls_back_to_retained_container_id(self):
        from types import SimpleNamespace
        from runner.research_loop import cleanup_own_workers
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); own=root/'candidate-001'; own.mkdir()
            identity='b'*64
            (own/'container.json').write_text(json.dumps({'Id':identity}))
            with patch('runner.research_loop.command',return_value=SimpleNamespace(returncode=0,stdout='')) as cmd:
                result=cleanup_own_workers(root)
            self.assertTrue(result['all_removed'])
            cmd.assert_called_once_with(['docker','ps','-aq','--no-trunc','--filter','id='+identity],timeout=15)

    def test_worker_cleanup_continues_after_one_inspection_failure(self):
        import subprocess
        from types import SimpleNamespace
        from runner.research_loop import cleanup_own_workers
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for number in (1,2):
                own=root/f'candidate-{number:03d}'; own.mkdir()
                (own/'worker.json').write_text(json.dumps({'container_name':'sciresearch-w-'+str(number)*12}))
            with patch('runner.research_loop.command',side_effect=[subprocess.TimeoutExpired('docker',1),SimpleNamespace(returncode=0,stdout='')]) as cmd:
                result=cleanup_own_workers(root)
            self.assertFalse(result['all_removed'])
            self.assertEqual(cmd.call_count,2)
            self.assertIn('candidate-001',result['errors'])
            self.assertEqual(result['records'][1]['status'],'removed_or_absent')

    def test_worker_cleanup_rejects_unscoped_names_and_symlink_metadata(self):
        from runner.research_loop import cleanup_own_workers
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            first=root/'candidate-001'; first.mkdir()
            (first/'worker.json').write_text(json.dumps({'container_name':'unrelated-service'}))
            second=root/'candidate-002'; second.mkdir()
            (second/'worker.json').symlink_to(first/'worker.json')
            with patch('runner.research_loop.command') as cmd:
                result=cleanup_own_workers(root)
            self.assertFalse(result['all_removed'])
            self.assertEqual(len(result['errors']),2)
            cmd.assert_not_called()

    def test_stop_and_inspection_failures_still_cleanup_and_save_result(self):
        import argparse,asyncio,contextlib,os,subprocess
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from runner.research_loop import run
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); inp=base/'input'; inp.mkdir()
            cases=[]
            for level in range(3):
                for number in range(2):
                    identifier=f'c{level}{number}'; path=inp/'cases'/identifier;path.mkdir(parents=True)
                    for name in ('metadata.json','observations.csv','target_grid.npy'): (path/name).write_bytes(b'public')
                    cases.append({'id':identifier,'path':'cases/'+identifier,'level':level})
            (inp/'manifest.json').write_text(json.dumps({'contract_version':'0.3.0','task':'heat','split':'public-dev','cases':cases}))
            fake=SimpleNamespace(start=AsyncMock(),upload_dir=AsyncMock(),exec=AsyncMock(side_effect=RuntimeError('setup refused')),stop=AsyncMock())
            calls=[]
            def cmd(argv,**kwargs):
                calls.append(argv)
                if argv[1:3]==['image','inspect']: text='[{"Id":"test-image"}]'
                elif argv[1:3]==['ps','-q']: text='cid\nsid\n'
                elif argv[1]=='inspect':
                    host={'CapAdd':[],'CapDrop':['ALL'],'SecurityOpt':[],'PidsLimit':128,'Memory':1073741824,'MemorySwap':1073741824,'NanoCpus':1000000000,'NetworkMode':'container:sid','PidMode':'','Privileged':False}
                    text=json.dumps([{'Id':cid,'Image':'test-image','Config':{'User':'researcher','Labels':{'com.docker.compose.service':service}},'Mounts':[],'HostConfig':host if service=='main' else dict(host,Memory=134217728,MemorySwap=134217728,NanoCpus=250000000)} for cid,service in [('cid','main'),('sid','harbor-docker-egress-control-sidecar')]])
                elif argv[1]=='stop' or argv[1:3]==['ps','-aq']: raise subprocess.TimeoutExpired(argv,1)
                else: text=''
                return SimpleNamespace(returncode=0,stdout=text,stderr='')
            args=argparse.Namespace(output_root=base/'attempt',input_root=inp,budget_seconds=300,parent_attempt=None,image='test',worker_image='test',expected_image_id='test-image')
            with patch.dict(os.environ,{'ANTHROPIC_AUTH_TOKEN':'fake-model-secret','ANTHROPIC_BASE_URL':'https://api.deepseek.com/anthropic'}), patch('runner.research_loop.DockerEnvironment',return_value=fake),patch('runner.research_loop.command',side_effect=cmd),contextlib.redirect_stdout(io.StringIO()):
                asyncio.run(run(args))
            result=json.loads((base/'attempt/result.json').read_text())
            fake.stop.assert_awaited_once()
            self.assertEqual(result['attempt_status'],'infrastructure_failed')
            self.assertIn('research_stop',result['cleanup_errors'])
            self.assertIn('containers_inspection',result['cleanup_errors'])
            self.assertTrue(any(c[1:3]==['network','ls'] for c in calls))
            self.assertTrue(any(c[1:3]==['volume','ls'] for c in calls))
            self.assertFalse(result['model_run_started'])


if __name__ == '__main__':
    unittest.main()
