import json
blocks=[]
for i in range(80):
    block=bytearray(64*1024**2)
    block[::4096]=b'\xa5'*(len(block)//4096)
    blocks.append(block)
    if (i+1)%4==0: print(json.dumps({'touched_bytes':(i+1)*64*1024**2}),flush=True)
raise SystemExit('memory limit was not enforced')
