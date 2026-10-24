import os,sys
out=None; inp=None
for i,a in enumerate(sys.argv):
    if a=='--output': out=sys.argv[i+1]
    if a=='--input': inp=sys.argv[i+1]
print("OUT",out,"IN",inp)
print("out exists",os.path.exists(out))
if os.path.exists(out):
    print("out listing",os.listdir(out))
print("in listing",os.listdir(inp) if inp and os.path.exists(inp) else None)
