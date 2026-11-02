"""Join trusted registrations/usage with observed native tool events, without guessing experiments."""
import json
from pathlib import Path
import re

from .common import canonical, digest, file_hash, read_json, write_json


def json_lines(path):
    if not path.exists():
        return []
    records=[]
    for line in path.read_text(errors='replace').splitlines():
        try:
            item=json.loads(line)
        except ValueError:
            continue
        if isinstance(item,dict):records.append(item)
    return records


def attempt_timeline(root):
    root=Path(root)
    state_path=root/'registry/state.json'
    state=read_json(state_path) if state_path.exists() else {}
    native=root/'auxiliary-agent/pi.txt'
    active={};tools=[];compactions=[]
    for event in json_lines(native):
        kind=event.get('type','')
        if 'compaction' in kind:
            compactions.append(event)
        if kind=='tool_execution_start':
            args=event.get('args') or {}
            active[event['toolCallId']]={'tool_call_id':event['toolCallId'],'name':event.get('toolName'),
                'args_sha256':digest(canonical(args)),'command':args.get('command'),'path':args.get('path'),
                'requested_timeout_seconds':args.get('timeout'),
                'started_at':event.get('benchTimestampMs',0)/1000 or None,
                'started_monotonic_ms':event.get('benchMonotonicMs')}
        elif kind=='tool_execution_end':
            row=active.pop(event['toolCallId'],{'tool_call_id':event['toolCallId'],'name':event.get('toolName')})
            end=event.get('benchMonotonicMs');start=row.pop('started_monotonic_ms',None)
            result=event.get('result') or {}
            content='\n'.join(b.get('text','') for b in result.get('content',[]) if b.get('type')=='text')
            code=re.search(r'Command exited with code (\d+)',content)
            status='error' if event.get('isError') else 'completed'
            if 'timed out' in content.lower():status='timeout'
            row.update(finished_at=event.get('benchTimestampMs',0)/1000 or None,
                       duration_seconds=(end-start)/1000 if isinstance(start,(int,float)) and isinstance(end,(int,float)) and end>=start else None,
                       status=status,result_sha256=digest(canonical(result)),
                       exit_code=int(code.group(1)) if code else (0 if row['name']=='bash' and status=='completed' else None),
                       error_excerpt=content[-1000:] if event.get('isError') else None)
            tools.append(row)
    for row in active.values():
        row.pop('started_monotonic_ms',None)
        tools.append({**row,'status':'no_end_event','duration_seconds':None})
    relay_path=root/'relay-evidence/evidence/events.jsonl'
    if not relay_path.exists():relay_path=root/'relay-evidence/events.jsonl'
    relay=json_lines(relay_path)
    evaluations=state.get('evaluations',[])
    candidates=[{'candidate_id':r['id'],'source_hash':r.get('source_hash'),'artifact_valid':r.get('artifact_valid'),
                 'accepted_at':r.get('accepted_at'),'completed_at':r.get('completed_at'),
                 'elapsed_since_research_start':r.get('accepted_at',0)-state['started_at'],
                 'attempt_status':r.get('result',{}).get('attempt_status')} for r in evaluations]
    valid=[r for r in candidates if r['artifact_valid']]
    bash=[r for r in tools if r['name']=='bash']
    first=next((r for r in candidates if r['candidate_id']==state.get('first_id')),None)
    references={str(p.relative_to(root)):file_hash(p) for p in (state_path,native,relay_path) if p.exists()}
    return {'summary':{'accepted_public_evaluations':len(evaluations),
              'unique_registered_source_hashes':len({r['source_hash'] for r in candidates if r['source_hash']}),
              'unique_valid_source_hashes':len({r['source_hash'] for r in valid if r['source_hash']}),
              'first_valid_registration_seconds':first['elapsed_since_research_start'] if first else None,
              'first_id':state.get('first_id'),'final_id':state.get('final_id'),'selection_reason':state.get('selection_reason'),
              'observed_tool_calls':len(tools),'observed_shell_commands':len(bash),
              'observed_shell_commands_other_than_bench':sum(not re.search(r'\bbench\s+(evaluate|finalize)\b',r.get('command') or '') for r in bash),
              'successful_model_requests':sum(r.get('event')=='request_finished' and r.get('outcome')=='success' for r in relay),
              'known_output_tokens':sum(r.get('output_tokens') or 0 for r in relay if r.get('event')=='request_finished'),
              'charged_output_tokens':sum(r.get('charged_output_tokens') or 0 for r in relay if r.get('event')=='request_finished'),
              'native_compaction_requests':sum(r.get('request_kind')=='native_compaction' for r in relay),
              'one_token_requests':sum(r.get('event')=='request_accepted' and r.get('effective_max_tokens')==1 for r in relay)},
            'candidate_versions':candidates,'tools':tools,'compaction_events':compactions,
            'budget_reminders':[r for r in relay if r.get('event')=='research_budget_reminder'],
            'evidence_sha256':references,
            'measurement_scope':'Tool durations use frozen native monotonic timestamps, not scorer timings. Source registration and usage are host records. Shell commands are observable activity, not a count of all internal experiments. Native logs are auxiliary evidence; incomplete tool durations remain null.'}


def build_timeline(project, plan, output):
    project=Path(project)
    ledger=read_json(project/'research-runs'/plan['plan_id']/'manifest.json')
    rows=[]
    for entry in ledger['attempts']:
        result=read_json(project/entry['result']['path'])
        root=(project/entry['registry']['path']).parent.parent if entry.get('registry') else project/'research-runs'/entry['run_id']
        row={'run_id':entry['run_id'],'attempt_id':entry['attempt_id'],'parent_attempt':entry.get('parent_attempt'),
             'attempt_status':result['attempt_status'],**attempt_timeline(root)}
        rows.append(row)
    value={'plan_id':plan['plan_id'],'scientific_sessions':len(plan['runs']),'attempts':rows}
    write_json(Path(output),value)
    return value
