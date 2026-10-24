"""Project-owned Docker transport for a fixed-provider, quota-limited model relay.

Only the random short-lived relay token reaches R. The provider credential is
passed by environment-variable name to the trusted relay container. This module
never serializes that credential or full Docker Config.Env inspection output.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import time
import uuid

from .common import file_hash, read_json, write_json

PORT = 8787
MODEL = "deepseek-flash"
NETWORK_PREFIX = "sciresearch-relay-"


def docker(*args, timeout=30, check=True, input=None, env=None):
    result = subprocess.run(["docker", *args], input=input, env=env,
                            capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        # No arguments or request bytes are included in error messages.
        raise RuntimeError(f"Docker {args[0]} failed with exit code {result.returncode}")
    return result


def validate_admission(admission):
    if admission.get("schema_version") != 1 or admission.get("model") != MODEL:
        raise ValueError("Unrecognized relay admission")
    for key in ("container_name", "network_name"):
        if not re.fullmatch(NETWORK_PREFIX + r"[0-9a-f]{12}", admission.get(key, "")):
            raise ValueError("Relay resources must have an exact per-run identity")
    if not re.fullmatch(r"[0-9a-f]{64}", admission.get("container_id", "")):
        raise ValueError("Invalid relay container identity")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", admission.get("image_id", "")):
        raise ValueError("Relay requires an immutable image ID")
    address = ipaddress.ip_address(admission["relay_ip"])
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
        raise ValueError("Relay must use its private Docker IPv4 address")
    if admission.get("relay_port") != PORT or admission.get("base_url") != f"http://{address}:{PORT}":
        raise ValueError("Relay URL must match the inspected IP and port")
    if not re.fullmatch(r"[0-9a-f]{64}", admission.get("token", "")):
        raise ValueError("Invalid short-lived relay token")
    return admission


def load_admission(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
        raise ValueError("Relay admission must be an owner-only regular file")
    if info.st_size > 16384:
        raise ValueError("Relay admission is too large")
    return validate_admission(read_json(path))


def relay_overlay(admission):
    validate_admission(admission)
    return {"services": {"harbor-docker-egress-control-sidecar": {"networks": ["bench_model_transport"]}},
            "networks": {"bench_model_transport": {"external": True, "name": admission["network_name"]}}}


_LOCAL_GET = """import json,sys,urllib.request
config=json.load(sys.stdin)
headers={'x-api-key':config['token']} if config.get('token') else {}
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(urllib.request.Request('http://127.0.0.1:8787'+config['path'],headers=headers),timeout=3) as response:
    data=response.read(65537)
    if len(data)>65536: raise ValueError('oversize relay response')
    print(json.dumps(json.loads(data)))
"""


def read_status(admission):
    validate_admission(admission)
    result = docker("exec", "-i", admission["container_id"], "python", "-I", "-c", _LOCAL_GET,
                    input=json.dumps({"path": "/status", "token": admission["token"]}), timeout=8)
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("Relay status must be an object")
    return value


def start_relay(output, *, image, provider_key=None, session_seconds=600,
                session_output_limit=32768, request_output_limit=4096,
                expected_system_sha256=None, expected_tools_sha256=None,
                expected_compaction_system_sha256=None, max_requests=512):
    from .model_relay import Limits
    Limits(session_seconds=session_seconds, session_output_limit=session_output_limit,
           request_output_limit=request_output_limit, expected_system_sha256=expected_system_sha256,
           expected_tools_sha256=expected_tools_sha256,
           expected_compaction_system_sha256=expected_compaction_system_sha256, max_requests=max_requests)
    secret = provider_key if provider_key is not None else os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if not secret:
        raise ValueError("Provider credential unavailable")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    output.chmod(0o700)
    evidence = output / "evidence"
    evidence.mkdir(mode=0o777)
    evidence.chmod(0o777)  # Only this trusted container receives this one directory.
    identity = NETWORK_PREFIX + uuid.uuid4().hex[:12]
    token = secrets.token_hex(32)
    source = output / "model_relay.py"
    source.write_bytes(Path(__file__).with_name("model_relay.py").read_bytes())
    source.chmod(0o444)
    image_info = json.loads(docker("image", "inspect", image).stdout)[0]
    image_id = image_info["Id"]
    record = {"formal": False, "identity": identity, "image_id": image_id,
              "relay_source_sha256": file_hash(source), "provider_key_in_R": False,
              "provider_endpoint": "https://api.deepseek.com/anthropic/v1/messages",
              "session_seconds": session_seconds, "session_output_limit": session_output_limit,
              "request_output_limit": request_output_limit, "status": "starting",
              "max_requests": max_requests,
              "expected_system_sha256": expected_system_sha256, "expected_tools_sha256": expected_tools_sha256,
              "expected_compaction_system_sha256": expected_compaction_system_sha256}
    write_json(output / "startup.json", record)
    try:
        docker("network", "create", "--driver", "bridge", "--label", "sciresearch.project=benchmark-v0.3", identity)
        environment = os.environ.copy()
        environment.update(BENCH_RELAY_PROVIDER_KEY=secret, BENCH_RELAY_SESSION_TOKEN=token)
        expected_args = ([] if expected_system_sha256 is None else
                         ["--expected-system-sha256", expected_system_sha256, "--expected-tools-sha256", expected_tools_sha256])
        if expected_compaction_system_sha256 is not None:
            expected_args += ["--expected-compaction-system-sha256", expected_compaction_system_sha256]
        docker("create", "--name", identity, "--label", "sciresearch.project=benchmark-v0.3",
               "--network", identity, "--cpus", "0.25", "--memory", "256m", "--memory-swap", "256m",
               "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--read-only", "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16777216",
               "--mount", f"type=bind,src={source},dst=/trusted/model_relay.py,readonly",
               "--mount", f"type=bind,src={evidence},dst=/evidence",
               "--env", "BENCH_RELAY_PROVIDER_KEY", "--env", "BENCH_RELAY_SESSION_TOKEN", image_id,
               "python", "-I", "/trusted/model_relay.py", "--bind", "0.0.0.0", "--port", str(PORT),
               "--events", "/evidence/events.jsonl", "--model", MODEL,
               "--session-seconds", "none" if session_seconds is None else str(session_seconds), "--session-output-limit", str(session_output_limit),
               "--request-output-limit", str(request_output_limit), "--max-requests", "none" if max_requests is None else str(max_requests),
               *expected_args, env=environment)
        docker("start", identity)
        info = json.loads(docker("inspect", identity).stdout)[0]
        admission = {"schema_version": 1, "model": MODEL, "token": token,
                     "container_name": identity, "container_id": info["Id"], "network_name": identity,
                     "relay_ip": info["NetworkSettings"]["Networks"][identity]["IPAddress"],
                     "relay_port": PORT, "image_id": image_id,
                     "admission_path": str(output / "admission.json"), "output_root": str(output)}
        admission["base_url"] = f"http://{admission['relay_ip']}:{PORT}"
        validate_admission(admission)
        ready = None
        for _ in range(30):
            health = docker("exec", "-i", admission["container_id"], "python", "-I", "-c", _LOCAL_GET,
                            input=json.dumps({"path": "/health"}), check=False, timeout=5)
            if health.returncode == 0:
                ready = json.loads(health.stdout)
                break
            time.sleep(.1)
        if ready is None:
            raise RuntimeError("Trusted relay did not become ready")
        # Never write the token using a temporary file with permissive umask.
        fd = os.open(output / "admission.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(admission, stream, sort_keys=True)
            stream.write("\n")
        record.update(status="ready", container_id=info["Id"], relay_ip=admission["relay_ip"],
                      health=ready, host_config={key: info["HostConfig"][key] for key in
                      ("CapDrop", "SecurityOpt", "PidsLimit", "Memory", "MemorySwap", "NanoCpus", "ReadonlyRootfs")},
                      mount_destinations=[row["Destination"] for row in info["Mounts"]])
        write_json(output / "startup.json", record)
        return admission
    except BaseException as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}".replace(secret, "[REDACTED]").replace(token, "[REDACTED]"))
        # A timed-out create can still have succeeded in the daemon. Attempt
        # each exact, newly generated name independently and preserve errors.
        record["failure_cleanup"] = {}
        for kind, args in (("container", ("rm", "-f", identity)), ("network", ("network", "rm", identity))):
            try:
                record["failure_cleanup"][kind] = {"returncode": docker(*args, check=False).returncode}
            except BaseException as cleanup_error:
                record["failure_cleanup"][kind] = {"error_type": type(cleanup_error).__name__}
        write_json(output / "startup.json", record)
        raise


def lock_rules(admission):
    validate_admission(admission)
    # Before native GOST's output DNAT: hostname/SNI spoofing cannot grant an
    # external destination. GOST's own marked upstream connection is restricted
    # by the same destination rule. DNS is unnecessary with a fixed numeric IP.
    return f"""add table inet bench_model_relay
flush table inet bench_model_relay
table inet bench_model_relay {{
  chain output {{
    type filter hook output priority -150; policy drop;
    ip daddr 127.0.0.11 drop
    udp dport 53 drop
    tcp dport 53 drop
    oifname "lo" tcp dport 12345 accept
    oifname "lo" tcp sport 12345 accept
    ip daddr {admission['relay_ip']} tcp dport {PORT} accept
  }}
}}
"""


_PROBE = """import json,socket,urllib.request,urllib.error,pathlib,struct
base=BASE_URL
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
rows=[]
for label,url,headers in [('relay',base+'/health',{}),('provider','https://api.deepseek.com',{}),('internet','http://1.1.1.1',{}),('spoofed_host','http://1.1.1.1',{'Host':base.split('//')[1]})]:
    row={'label':label,'http_response':False}
    try:
        with opener.open(urllib.request.Request(url,headers=headers),timeout=2) as response:
            row.update(http_response=True,status=response.status)
            if label=='relay': row['health']=json.loads(response.read(65536))
    except urllib.error.HTTPError as exc: row.update(http_response=True,status=exc.code)
    except Exception as exc: row['error_type']=type(exc).__name__
    rows.append(row)
raw=socket.socket();raw.settimeout(2)
try: raw.connect(('1.1.1.1',443)); raw_connected=True
except OSError: raw_connected=False
finally: raw.close()
resolvers=[line.split()[1] for line in pathlib.Path('/etc/resolv.conf').read_text().splitlines() if line.strip().startswith('nameserver ')]
targets={(address,53,protocol) for address in resolvers for protocol in ('udp','tcp')}
for protocol in ('udp','tcp'):
    for line in pathlib.Path('/proc/net/'+protocol).read_text().splitlines()[1:]:
        parts=line.split()
        address,port=parts[1].split(':')
        address=socket.inet_ntoa(bytes.fromhex(address)[::-1])
        if address in resolvers and (protocol=='udp' or parts[3]=='0A'):
            targets.add((address,int(port,16),protocol))
name=b''.join(bytes([len(part)])+part for part in (b'relay-egress-probe',b'invalid'))+b'\\x00'
query=struct.pack('!HHHHHH',17963,256,1,0,0,0)+name+struct.pack('!HH',1,1)
dns=[]
for address,port,protocol in sorted(targets):
    row={'address':address,'port':port,'protocol':protocol,'response_received':False}
    family=socket.AF_INET6 if ':' in address else socket.AF_INET
    sock=socket.socket(family,socket.SOCK_DGRAM if protocol=='udp' else socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        if protocol=='udp':
            sock.sendto(query,(address,port)); row['response_received']=bool(sock.recvfrom(4096)[0])
        else:
            sock.connect((address,port)); sock.sendall(struct.pack('!H',len(query))+query); row['response_received']=bool(sock.recv(4096))
    except OSError as exc: row['error_type']=type(exc).__name__
    finally: sock.close()
    dns.append(row)
print(json.dumps({'checks':rows,'external_raw_tcp_connected':raw_connected,'dns_resolvers':resolvers,'dns_checks':dns}))
"""


async def lock_and_probe(environment, admission, evidence_dir):
    from harbor.models.task.config import NetworkMode, NetworkPolicy
    validate_admission(admission)
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    policy = NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=[admission["relay_ip"]])
    await asyncio.wait_for(environment.set_network_policy(policy), 30)
    rules = lock_rules(admission)
    installed = await environment.service_exec("printf %s " + shlex.quote(rules) + " | nft -f -",
        service="harbor-docker-egress-control-sidecar", timeout_sec=10)
    if installed.return_code:
        raise RuntimeError("Relay destination firewall could not be installed")
    verified = await environment.service_exec("nft list table inet bench_model_relay",
        service="harbor-docker-egress-control-sidecar", timeout_sec=10)
    (evidence_dir / "nft-rules.txt").write_text(verified.stdout or "")
    if verified.return_code or "policy drop" not in (verified.stdout or "") or admission["relay_ip"] not in (verified.stdout or ""):
        raise RuntimeError("Relay destination firewall could not be verified")
    probe_code = _PROBE.replace("BASE_URL", repr(admission["base_url"]))
    response = await environment.exec(command="python -I -c " + shlex.quote(probe_code), timeout_sec=30)
    if response.return_code:
        raise RuntimeError("Actual R relay admission probe failed")
    result = json.loads(response.stdout)
    result.update(formal=False, firewall="container sidecar namespace only; exact IP/port before GOST DNAT",
                  relay_ip=admission["relay_ip"], relay_port=PORT, model_calls=0)
    rows = result["checks"]
    result["passed"] = (len(rows)==4 and rows[0]["label"]=="relay" and rows[0]["http_response"]
                        and rows[0].get("status")==200 and all(not row["http_response"] for row in rows[1:])
                        and result["external_raw_tcp_connected"] is False and bool(result["dns_resolvers"])
                        and bool(result["dns_checks"]) and all(not row["response_received"] for row in result["dns_checks"]))
    write_json(evidence_dir / "result.json", result)
    if not result["passed"]:
        raise RuntimeError("Relay reachable/provider-direct blocked admission did not pass")
    return result


def cleanup_relay(admission):
    validate_admission(admission)
    result = {"container_id": admission["container_id"], "network_name": admission["network_name"], "errors": {}}
    try:
        result["status_before_stop"] = read_status(admission)
    except Exception as exc:
        result["errors"]["status"] = type(exc).__name__
    for key, args in (("container", ("rm", "-f", admission["container_id"])),
                      ("network", ("network", "rm", admission["network_name"]))):
        try:
            removed = docker(*args, check=False)
            result[key + "_remove_returncode"] = removed.returncode
            if removed.returncode:
                result["errors"][key] = "Docker removal was not successful"
        except Exception as exc:
            result["errors"][key] = type(exc).__name__
    for key, args in (("containers", ("ps", "-aq", "--no-trunc", "--filter", "id="+admission["container_id"])),
                      ("networks", ("network", "ls", "-q", "--filter", "name=^"+admission["network_name"]+"$"))):
        try:
            result["remaining_" + key] = docker(*args).stdout.split()
        except Exception as exc:
            result["remaining_" + key] = ["inspection_failed"]
            result["errors"][key + "_inspection"] = type(exc).__name__
    result["all_removed"] = not result["remaining_containers"] and not result["remaining_networks"]
    if admission.get("output_root"):
        write_json(Path(admission["output_root"]) / "cleanup.json", result)
    return result
