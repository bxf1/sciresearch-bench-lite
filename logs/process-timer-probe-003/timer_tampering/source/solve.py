import argparse,json,os,time,errno,signal
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser()
p.add_argument('--input',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--seed')
a=p.parse_args()
cases=json.loads((a.input/'manifest.json').read_text())['cases']
def zeros():
    for case in cases:
        d=a.output/'cases'/case['id']
        d.mkdir(parents=True,exist_ok=True)
        np.save(d/'u0.npy',np.zeros(256,dtype='<f8'),allow_pickle=False)
import ctypes,resource,socket
checks={}
def denied(name, action):
    try: action(); checks[name]=False
    except (PermissionError,FileNotFoundError,ConnectionRefusedError): checks[name]=True
denied('kill_init',lambda:os.kill(1,signal.SIGKILL))
denied('stop_init',lambda:os.kill(1,signal.SIGSTOP))
denied('prlimit_init',lambda:resource.prlimit(1,resource.RLIMIT_NOFILE,(1,1)))
denied('write_record',lambda:Path('/tmp/.sciresearch-timer-private/result.json').write_text('{}'))
denied('unlink_private_dir',lambda:Path('/tmp/.sciresearch-timer-private').rmdir())
denied('read_init_memory',lambda:open('/proc/1/mem','rb'))
denied('write_init_stdout',lambda:open('/proc/1/fd/1','wb'))
denied('second_handshake',lambda:socket.socket(socket.AF_UNIX).connect('/tmp/.sciresearch-timer/launch.sock'))
lib=ctypes.CDLL(None,use_errno=True)
checks['ptrace_init']=lib.ptrace(16,1,None,None)==-1 and ctypes.get_errno()==1
checks['no_inherited_socket']=all(not os.readlink('/proc/self/fd/'+fd).startswith('socket:') for fd in os.listdir('/proc/self/fd') if fd.isdigit() and os.path.exists('/proc/self/fd/'+fd))
checks['uid65534']=os.getuid()==65534
status=Path('/proc/self/status').read_text()
checks['no_capabilities']='CapEff:\t0000000000000000' in status
checks['no_new_privileges']='NoNewPrivs:\t1' in status
print(json.dumps(checks),flush=True)
assert all(checks.values()),checks
zeros()
