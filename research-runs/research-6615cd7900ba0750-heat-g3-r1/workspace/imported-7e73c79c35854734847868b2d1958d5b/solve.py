import os,sys,json
info={"argv":sys.argv,"cwd":os.getcwd(),"env":{k:v for k,v in os.environ.items() if any(s in k.upper() for s in ('BENCH','INPUT','OUTPUT','CASE','TASK','SEED'))}}
open('/workspace/probe_info.json','w').write(json.dumps(info,indent=1))
