"""Per-run narrow HTTP bridge. Only host-owned configuration selects W and inputs."""
from __future__ import annotations
import argparse
import hmac
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
from pathlib import Path
import secrets
import time
from .common import read_json,write_json
from .registry import Registry
from .public_evaluation import run_public_evaluation

def handler(registry,task,input_root,image,token,*,execute=None,check=None):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self,*_):
            pass  # Never put Authorization headers into logs.

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+token):
                self.send_error(403)
                return
            try:
                length=int(self.headers.get("Content-Length","-1"))
                if length<0 or length>4096 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("request length not allowed")
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):
                    raise ValueError("request must be an object")
                if self.path=="/evaluate" and set(body)=={"path"} and isinstance(body["path"],str):
                    def evaluate(snapshot,candidate_id,remaining):
                        run=registry.root/"evaluations"/candidate_id
                        return run_public_evaluation(task,snapshot,input_root,run,image,remaining,execute=execute,check=check)
                    row=registry.evaluate(body["path"],evaluate)
                    response={"candidate_id":row["id"],"source_hash":row["source_hash"],"feedback":row["result"]}
                elif self.path=="/finalize" and set(body)=={"candidate_id"} and isinstance(body["candidate_id"],str):
                    registry.finalize(body["candidate_id"])
                    response={"finalized":body["candidate_id"]}
                else:
                    raise ValueError("unknown action or fields")
                data=json.dumps(response,allow_nan=False).encode()
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (ValueError,OSError) as exc:
                data=json.dumps({"error":str(exc)}).encode()
                self.send_response(400)
                self.send_header("Content-Length",str(len(data)))
                self.end_headers()
                self.wfile.write(data)
    return Handler

def serve(registry,task,input_root,image,token,host="127.0.0.1",port=0,*,execute=None,check=None):
    return HTTPServer((host,port),handler(registry,task,Path(input_root),image,token,execute=execute,check=check))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("registry","input","task","image","token-file"):
        p.add_argument("--"+name,required=True)
    p.add_argument("--host",default="127.0.0.1")
    p.add_argument("--port",type=int,default=0)
    a=p.parse_args()
    token=Path(a.token_file).read_text().strip()
    if len(token)<32:
        raise ValueError("bridge token too short")
    server=serve(Registry(a.registry),a.task,a.input,a.image,token,a.host,a.port)
    print(json.dumps({"address":server.server_address,"run":str(a.registry)}),flush=True)
    server.serve_forever()
