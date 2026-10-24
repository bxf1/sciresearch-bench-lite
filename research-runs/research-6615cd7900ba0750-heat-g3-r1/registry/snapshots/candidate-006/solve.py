import os,sys,json
print("ARGV",sys.argv)
print("CWD",os.getcwd())
print("ENV",{k:v for k,v in os.environ.items() if any(s in k.upper() for s in ('BENCH','INPUT','OUTPUT','CASE','TASK','SEED'))})
print("LS",os.listdir('.'))
