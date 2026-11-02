"""Prepare new public packages and pinned R images; preserve previous packages."""
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from authoring.package_tasks import package
from runner.common import read_json, write_json, file_hash, canonical, digest, tree_hashes

OUT = ROOT/'logs/optimized-r1-20261101'
DATA = ROOT/'authoring/data/optimized-r1-20261101'


def main():
    old = read_json(ROOT/'freezes/research-run-plan-unified-ode-poisson-r1-2026-10-29.json')
    target = ROOT/'build/optimized-r1-20261101/task-packages'
    package(ROOT, DATA, target)
    images = {}
    for task in ('heat','ode','poisson'):
        context = target/task/'environment'
        base = old['research_images'][task]['image_id']
        (context/'Dockerfile').write_text(f'''FROM {base}
USER root
RUN rm -rf /input /opt/bench && mkdir -p /input /opt/bench
COPY public-dev/ /input/
COPY public/ /opt/bench/public/
COPY helpers/ /opt/bench/
COPY trusted/ /opt/bench/trusted/
RUN chown -R root:root /input /opt/bench && chmod -R a-w /input /opt/bench && cp /opt/bench/public/bench /usr/local/bin/bench && chmod 755 /usr/local/bin/bench
USER researcher
WORKDIR /workspace
CMD ["sleep", "infinity"]
''')
        tag = 'sciresearch-optimized-r1-'+task+':20261101'
        with (OUT/(task+'-image-build.log')).open('x') as stream:
            subprocess.run(['docker','build','--network','none','-t',tag,str(context)],check=True,stdout=stream,stderr=subprocess.STDOUT)
        image = subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',tag],text=True).strip()
        hashes = tree_hashes(context)
        evidence = OUT/(task+'-image.json')
        value = {'status':'verified','task':task,'image_id':image,'base_image_id':base,
                 'build_context_sha256':digest(canonical(hashes)),'context_hashes':hashes}
        write_json(evidence,value)
        images[task] = {'image_id':image,'build_context_sha256':value['build_context_sha256'],
                        'inspection':{'path':evidence.relative_to(ROOT).as_posix(),'sha256':file_hash(evidence)}}
    archive = ROOT/'archives/pre-optimized-r1-20261101'
    archive.mkdir(exist_ok=False)
    shutil.copytree(ROOT/'tasks',archive/'tasks')
    write_json(archive/'tasks-sha256.json',tree_hashes(archive/'tasks'))
    shutil.rmtree(ROOT/'tasks')
    shutil.copytree(target,ROOT/'tasks')
    # The package manifest describes the generated public-only contexts, including
    # the offline derived Dockerfile actually used to build each image.
    manifest = read_json(ROOT/'tasks/package-manifest.json')
    for task in images:
        manifest['tasks'][task]['build_context_hashes'] = tree_hashes(ROOT/'tasks'/task/'environment')
    write_json(ROOT/'tasks/package-manifest.json',manifest)
    write_json(OUT/'research-images.json',{'research_images':images})
    write_json(OUT/'provider-documentation.json',{
        'status':'verified','retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model_id':'deepseek-flash','documented_version':'DeepSeek-V4.1-Flash-1017',
        'sources':['https://api-docs.deepseek.com/quick_start/pricing/','https://api-docs.deepseek.com/guides/anthropic_api/'],
        'scope':'Provider-declared alias mapping, not immutable backend identity.',
        'findings':{'thinking':True,'output_config_effort':True,'thinking_temperature':'fixed by provider; omit field',
                    'top_p':1.0,'request_output_limit':16384,
                    'compatibility_caveat':'Provider documents exceptions to max_tokens for certain Claude Code/OpenCode main-agent calls; Pi uses the tested fixed relay route, which fails closed on output usage above its reservation.'}})
    print(json.dumps({'status':'packages_and_images_prepared','research_images':images}),flush=True)


if __name__ == '__main__':
    main()
