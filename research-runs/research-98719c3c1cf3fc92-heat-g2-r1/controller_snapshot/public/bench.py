#!/usr/bin/env python3
"""Research-side client. Only a relative source path or registered ID is accepted."""
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("evaluate","finalize"))
    parser.add_argument("value")
    args=parser.parse_args()
    config=json.loads(Path(os.environ.get("BENCH_BRIDGE_CONFIG","/run/bench/config.json")).read_text())
    body={"path" if args.action=="evaluate" else "candidate_id":args.value}
    request=urllib.request.Request(config["url"].rstrip("/")+"/"+args.action,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+config["token"]},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=1800) as response:
            print(response.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode())
        raise SystemExit(1)

if __name__=="__main__":
    main()
