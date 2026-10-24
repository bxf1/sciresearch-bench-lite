import os,sys
# write diagnostics into the output dir, which we can inspect via error messages
out=None
for i,a in enumerate(sys.argv):
    if a=='--output': out=sys.argv[i+1]
print("ARGV",sys.argv)
if out:
    os.makedirs(out,exist_ok=True)
    open(os.path.join(out,'ZZZ_diag.txt'),'w').write(repr(sys.argv)+"\n"+os.getcwd()+"\n"+repr(os.listdir('.')))
