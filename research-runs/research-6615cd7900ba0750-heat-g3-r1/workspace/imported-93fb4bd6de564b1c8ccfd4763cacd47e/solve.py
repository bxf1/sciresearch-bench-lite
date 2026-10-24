import os,sys,numpy as np
out=None
for i,a in enumerate(sys.argv):
    if a=='--output': out=sys.argv[i+1]
os.makedirs(out,exist_ok=True)
np.save(os.path.join(out,'output.npy'),np.zeros(256))
