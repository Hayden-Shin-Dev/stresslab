"""Local-only ordered research, preserving existing datasets and model releases."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]))
OUT=ROOT/'reports/exposure_universe_20261103'
SRC=ROOT/'data/research/exposure_universe_20261103'

def status(stage,**extra):
    data={'stage':stage,'updated_epoch':time.time(),**extra}
    p=OUT/'run_status.json';tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,indent=2),encoding='utf8');tmp.replace(p)
    print(json.dumps(data),flush=True)

def run(script,python=None,args=()):
    status(script)
    with (OUT/(Path(script).stem+'.log')).open('w',encoding='utf8') as log:
        subprocess.run([str(python or sys.executable),str(ROOT/'scripts'/script),*args],cwd=ROOT,stdout=log,stderr=log,check=True)

def main():
    status('waiting_for_existing_candidate_collection')
    while True:
        s=json.loads((SRC/'screen_progress.json').read_text(encoding='utf8'))
        if s['status']!='running':break
        if time.time()-(SRC/'screen_progress.json').stat().st_mtime>600:raise RuntimeError('Candidate collection stopped progressing')
        time.sleep(10)
    assert s['status']=='complete', 'Candidate collection requires repair'
    run('select_exposure_universe.py')
    selected=OUT/'selected_assets.json';pairs=OUT/'selected_asset_shock_pairs.csv'
    frozen={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [selected,pairs,OUT/'selection_protocol.json']}
    (OUT/'selection_frozen_before_evaluation.json').write_text(json.dumps(frozen,indent=2),encoding='utf8')
    assert json.loads(selected.read_text()), 'No selected stocks; do not relax the selection rules'
    run('collect_exposure_candidates.py',ROOT/'.venv-krx-batch/Scripts/python.exe',('--selected',))
    manifest=[{'file':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((SRC/'stocks').glob('*/*.json'))]
    (OUT/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    run('evaluate_exposure_universe.py')
    run('summarize_exposure_universe.py')
    run('ablate_selected_exposures.py')
    run('report_exposure_universe.py')
    for name,digest in frozen.items():assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest
    status('complete',selection_unchanged=True,production_approved=False)

if __name__=='__main__':
    try:main()
    except Exception as e:
        status('failed',error_type=type(e).__name__)
        raise
