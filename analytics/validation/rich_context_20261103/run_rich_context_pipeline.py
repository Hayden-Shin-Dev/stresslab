"""Wait for verified official collection, then build/train/report locally."""
import json,sys,time,subprocess,os
from pathlib import Path
ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]));OUT=ROOT/'reports/rich_context_20261103'
def status(stage,**kw):(OUT/'pipeline_status.json').write_text(json.dumps(dict(stage=stage,**kw),indent=2))
def main():
    status('waiting_for_official_sources')
    while True:
        states=[]
        for name in ['collection_progress.json','dart_progress.json']:
            try:states.append(json.loads((OUT/name).read_text())['status'])
            except (OSError,json.JSONDecodeError):states.append('waiting')
        if any(s in ['failed','partial'] for s in states):raise RuntimeError('Source collection incomplete')
        if all(s=='complete' for s in states):break
        time.sleep(5)
    scripts=['build_rich_context','train_rich_context','report_rich_context','diagnose_rich_context','audit_rich_context']
    if '--resume-training' in sys.argv:
        assert (OUT/'learning_table.parquet').exists()
        scripts=scripts[1:]
    for script in scripts:
        status(script)
        with (OUT/(script+'.log')).open('w',encoding='utf8') as log:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name(f'{script}.py'))],cwd=ROOT,stdout=log,stderr=log)
        if result.returncode:raise RuntimeError(script+' failed')
    status('complete',approved=False)
if __name__=='__main__':
    try:main()
    except Exception as e:status('failed',error=str(e));raise
