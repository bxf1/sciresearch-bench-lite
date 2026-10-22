import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runner import relay_transport as relay


def admission():
    return {"schema_version":1,"model":"deepseek-v4-pro","token":"a"*64,
            "container_name":"sciresearch-relay-"+"b"*12,"network_name":"sciresearch-relay-"+"b"*12,
            "container_id":"c"*64,"image_id":"sha256:"+"d"*64,"relay_ip":"172.31.0.2",
            "relay_port":8787,"base_url":"http://172.31.0.2:8787"}


@pytest.mark.parametrize('field,value',[('relay_ip','1.1.1.1'),('relay_ip','127.0.0.1'),
    ('network_name','user-database'),('container_id','unknown'),('base_url','https://api.deepseek.com'),
    ('relay_port',80),('token','short'),('image_id','latest')])
def test_rejects_resources_outside_exact_relay_admission(field,value):
    value_map=admission()
    value_map[field]=value
    with pytest.raises(ValueError):
        relay.validate_admission(value_map)


def test_admission_is_owner_only_and_never_a_symlink(tmp_path):
    path=tmp_path/'admission.json'
    path.write_text(json.dumps(admission()))
    path.chmod(0o644)
    with pytest.raises(ValueError):
        relay.load_admission(path)
    path.chmod(0o600)
    assert relay.load_admission(path)['relay_ip']=='172.31.0.2'
    alias=tmp_path/'link.json'
    alias.symlink_to(path)
    with pytest.raises(ValueError):
        relay.load_admission(alias)


def test_destination_lock_precedes_native_dnat_and_has_no_global_mark_bypass():
    rules=relay.lock_rules(admission())
    assert 'priority -150; policy drop;' in rules
    assert '172.31.0.2 tcp dport 8787 accept' in rules
    assert 'meta mark' not in rules
    assert 'ct state' not in rules
    assert rules.index('ip daddr 127.0.0.11 drop')<rules.index('oifname "lo"')
    assert 'udp dport 53 drop' in rules
    assert 'oifname "lo" accept' not in rules


class FakeEnvironment:
    def __init__(self,external_response=False):
        self.external_response=external_response
        self.policies=[]
    async def set_network_policy(self,policy):
        self.policies.append(policy)
    async def service_exec(self,command,**kwargs):
        return SimpleNamespace(return_code=0,stdout=relay.lock_rules(admission()),stderr='')
    async def exec(self,**kwargs):
        return SimpleNamespace(return_code=0,stdout=json.dumps({'checks':[
            {'label':'relay','http_response':True,'status':200},
            {'label':'provider','http_response':self.external_response},
            {'label':'internet','http_response':False},
            {'label':'spoofed_host','http_response':False}],
            'external_raw_tcp_connected':False,'dns_resolvers':['127.0.0.11'],
            'dns_checks':[{'address':'127.0.0.11','port':53,'protocol':'udp','response_received':False}]}))


def test_own_R_must_reach_relay_while_provider_and_spoofed_destinations_fail(tmp_path):
    environment=FakeEnvironment()
    proof=asyncio.run(relay.lock_and_probe(environment,admission(),tmp_path/'good'))
    assert proof['passed'] and proof['model_calls']==0
    assert environment.policies[0].allowed_hosts==['172.31.0.2']
    with pytest.raises(RuntimeError,match='blocked admission'):
        asyncio.run(relay.lock_and_probe(FakeEnvironment(True),admission(),tmp_path/'bad'))
    assert json.loads((tmp_path/'bad/result.json').read_text())['passed'] is False


def test_cleanup_is_exact_and_continues_after_removal_failure():
    calls=[]
    def fake(*args,**kwargs):
        calls.append(args)
        if args[0]=='rm':
            raise TimeoutError('failure')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    with patch.object(relay,'read_status',return_value={'request_count':0}),patch.object(relay,'docker',side_effect=fake):
        result=relay.cleanup_relay(admission())
    assert result['errors']['container']=='TimeoutError'
    assert ('network','rm',admission()['network_name']) in calls
    assert all('prune' not in args for args in calls)
    assert ('ps','-aq','--no-trunc','--filter','id='+admission()['container_id']) in calls


def test_status_token_goes_only_to_stdin():
    captured={}
    def fake(*args,**kwargs):
        captured.update(args=args,kwargs=kwargs)
        return SimpleNamespace(stdout='{"request_count":0}')
    with patch.object(relay,'docker',side_effect=fake):
        assert relay.read_status(admission())=={'request_count':0}
    assert admission()['token'] not in ' '.join(captured['args'])
    assert json.loads(captured['kwargs']['input'])['token']==admission()['token']
