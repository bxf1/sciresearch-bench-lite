"""Print current supplemental progress without reading hidden tests or credentials."""
from pathlib import Path
import argparse
import json

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'freezes/supplemental-500k-2026-10-24-recovery-003.json'

def read(path):
    return json.loads(path.read_text())

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=PLAN)
    args=parser.parse_args()
    plan=read(args.plan)
    ledger=ROOT/'research-runs'/plan['plan_id']/'manifest.json'
    entries={row['run_id']:row for row in read(ledger)['attempts']} if ledger.exists() else {}
    rows=[]
    for run in plan['runs']:
        settings=run['settings'];identifier=settings['run_id']
        entry=entries.get(identifier,{})
        row={'run_id':identifier,'task':settings['task'],'group':settings['group'],'repeat':settings['repeat'],
             'status':entry.get('status','not_started'),'output_token_limit':settings['session_output_limit'],
             'research_wall_seconds_limit':settings['research_seconds']}
        root=ROOT/'research-runs'/identifier
        if (root/'registry/state.json').exists():
            state=read(root/'registry/state.json')
            row.update(public_evaluations=len(state['evaluations']),first_id=state['first_id'],final_id=state['final_id'],closed=state['closed'])
        # Only public relay event evidence is read; admission credentials never are.
        events=root/'relay-evidence/evidence/events.jsonl'
        if not events.exists() and (root/'result.json').exists():
            info=read(root/'result.json')
            location=(info.get('relay') or {}).get('admission_path')
            if location:
                parent=Path(location).parent.resolve()
                if parent.is_relative_to((ROOT/'build').resolve()):events=parent/'evidence/events.jsonl'
        if events.exists():
            finished=[]
            for line in events.read_text().splitlines():
                try:event=json.loads(line)
                except json.JSONDecodeError:continue # A live append may have an incomplete final line.
                if event.get('event')=='request_finished':finished.append(event)
            row.update(completed_requests=len(finished),successful_requests=sum(x.get('outcome')=='success' for x in finished),
                       known_output_tokens=sum(x.get('output_tokens') or 0 for x in finished),
                       charged_output_tokens=sum(x.get('charged_output_tokens') or 0 for x in finished))
        rows.append(row)
    print(json.dumps({'study_kind':'selective_supplemental','hidden_data_read':False,'runs':rows},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
