import os,sys
print("ARGV",sys.argv)
print("CWD",os.getcwd())
for k,v in sorted(os.environ.items()):
    if 'BENCH' in k or 'INPUT' in k or 'OUTPUT' in k or 'CASE' in k: print(k,'=',v)
