import os,sys
out=None; inp=None
for i,a in enumerate(sys.argv):
    if a=='--output': out=sys.argv[i+1]
    if a=='--input': inp=sys.argv[i+1]
info=f"OUT={out} IN={inp} outexists={os.path.exists(out)} outlist={os.listdir(out) if out and os.path.exists(out) else None} inlist={os.listdir(inp) if inp and os.path.exists(inp) else None}"
for p in ['/workspace/probe_info.txt', os.path.join(os.path.dirname(os.path.abspath(__file__)),'info.txt'), '/tmp/probe_info.txt']:
    try:
        open(p,'w').write(info); 
    except Exception as e: pass
