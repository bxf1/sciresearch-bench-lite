import os,sys,numpy as np
out=None
for i,a in enumerate(sys.argv):
    if a=='--output': out=sys.argv[i+1]
print("OUT",out)
# try: output is a directory; write nothing but print listing of parent
if out:
    print("exists",os.path.exists(out),"isdir",os.path.isdir(out))
    print("parent",os.listdir(os.path.dirname(out.rstrip('/')) or '.'))
