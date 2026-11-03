"""Wait for current collector, then run selection and evaluation. No deploy/publish."""
import json,subprocess,sys,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/long_universe_20261103'
def state(stage,**kwargs):(OUT/'pipeline_status.json').write_text(json.dumps(dict(stage=stage,pid=os.getpid(),**kwargs),indent=2))
def main():
    state('waiting_for_collection')
    while True:
        try:s=json.loads((OUT/'collection_progress.json').read_text())
        except (OSError,json.JSONDecodeError):time.sleep(5);continue
        if s['status'] in ['failed','partial']:raise RuntimeError('Official collection incomplete; training not started')
        if s['status']=='complete':break
        time.sleep(5)
    for name in ['select_long_universe','train_long_universe','report_long_universe','summarize_long_universe']:
        state(name)
        with (OUT/(name+'.log')).open('w',encoding='utf8') as log:
            p=subprocess.run([sys.executable,str(ROOT/'scripts'/f'{name}.py')],cwd=ROOT,stdout=log,stderr=log)
        if p.returncode:raise RuntimeError(name+' failed; outputs not approved')
    state('complete',approved=False)
if __name__=='__main__':
    try:main()
    except Exception as e:state('failed',reason=str(e));raise
