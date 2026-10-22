import argparse,asyncio
from pathlib import Path
from runner.relay_transport import start_relay
from runner.harbor_pilot import run
root=Path.cwd()
admission=start_relay(root/'build/relay-native-pilot-002',image='sha256:e0018a98b2495aa3d53698362a4d890794c728d96e7bee618eeefa4d43e2fe6a',session_seconds=1500,session_output_limit=32768,request_output_limit=4096,expected_system_sha256='120b7c696c00bdce825e4711643679bee2c5b21a2b74ec2aa68cda2a4810ecae',expected_tools_sha256='99653ba38839a24430523861d5b974d2ccc9a68e1506a3aa0394880caa2c515a')
args=argparse.Namespace(public_input=root/'tasks/heat/environment/public-dev',pilot_input=root/'authoring/data/pilot-smoke/inputs/heat/pilot-smoke',pilot_truth=root/'authoring/data/pilot-smoke/private/heat/pilot-smoke',output_root=root/'logs/harbor-native-pilot-002',research_image='sha256:6619dd1526ec8d635d0e57d068dc3e750821ddd82443d44777fe847340944bdb',numeric_image='sha256:e0018a98b2495aa3d53698362a4d890794c728d96e7bee618eeefa4d43e2fe6a',relay_admission=Path(admission['admission_path']))
result=asyncio.run(run(args))
raise SystemExit(0 if result['status']=='pilot_completed' else 1)
