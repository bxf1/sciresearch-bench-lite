import hashlib,json,os,pathlib,shutil,subprocess
executable=shutil.which('pi')
assert executable, 'preinstalled Pi is missing; offline capture never installs packages'
root=pathlib.Path(executable).resolve().parent.parent
package=json.loads((root/'package.json').read_text())
assert package['name']=='@earendil-works/pi-coding-agent' and package['version']=='0.84.1', 'wrong Pi package/version'
version=subprocess.run(['pi','--version'],capture_output=True,text=True,timeout=15,check=True).stdout.strip()
assert version=='0.84.1', 'Pi executable version mismatch'
assert os.getuid()==1000 and os.getgid()==1000 and os.getcwd()=='/workspace'
manifest=json.loads(pathlib.Path('/input/manifest.json').read_text())
assert manifest['split']=='public-dev', 'capture image must contain public-dev only'
# With default native flags, any discovery source could change the wire policy.
# Fail closed instead of adding no-discovery flags that native Pi does not use.
discovery=[pathlib.Path('/tmp/harbor-pi-agent'),pathlib.Path('/workspace/.pi'),pathlib.Path('/.pi')]
assert not any(p.exists() for p in discovery), 'unexpected Pi discovery/config directory in fresh image'
contexts=[pathlib.Path('/AGENTS.md'),pathlib.Path('/workspace/AGENTS.md')]
assert not any(p.exists() for p in contexts), 'unexpected project context in fresh research image'
names=['package.json','dist/config.js','dist/core/system-prompt.js','dist/core/sdk.js',
 'dist/core/agent-session.js','dist/core/resource-loader.js','dist/core/extensions/runner.js',
 'dist/core/provider-composer.js','node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js',
 'node_modules/@earendil-works/pi-ai/dist/api/simple-options.js']
names+=sorted(p.relative_to(root).as_posix() for p in (root/'dist/core/tools').rglob('*.js'))
sources={name:(root/name).read_text() for name in names}
api=sources['node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js']
start=api.index('let params = buildParams(model, context, isOAuth, options);')
hook=api.index('await options?.onPayload?.(params, model)',start)
request=api.index('client.messages.create(',hook)
assert start<hook<request
assert 'return runner.emitBeforeProviderRequest(payload)' in sources['dist/core/sdk.js']
print(json.dumps({'version':version,'package_root':str(root),'uid':os.getuid(),'gid':os.getgid(),
 'cwd':os.getcwd(),'public_manifest':{k:manifest[k] for k in ('task','split')},
 'no_discovered_extensions_or_context':True,'native_hook_before_http':True,
 'source_sha256':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()},
 'sources':sources},ensure_ascii=True))
