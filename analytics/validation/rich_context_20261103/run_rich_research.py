"""Repository entry point using a separate, private historical data root."""
import argparse,os,sys,runpy
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-root',required=True)
    p.add_argument('--stage',choices=['build','train','report','diagnose','audit'],required=True)
    args=p.parse_args();root=Path(args.data_root).resolve()
    assert (root/'reports/long_universe_20261103/selected_assets.json').exists(),'Prior research data root required'
    os.environ['STRESSLAB_AUDIT_ROOT']=str(root)
    here=Path(__file__).resolve().parent
    # Published studies live in sibling folders; local development uses scripts/.
    if here.parent.name=='validation':
        for folder in sorted(here.parent.iterdir()):
            if folder.is_dir():sys.path.append(str(folder))
    sys.path.insert(0,str(here))
    names={'build':'build_rich_context','train':'train_rich_context','report':'report_rich_context','diagnose':'diagnose_rich_context','audit':'audit_rich_context'}
    runpy.run_path(str(here/(names[args.stage]+'.py')),run_name='__main__')

if __name__=='__main__':main()
