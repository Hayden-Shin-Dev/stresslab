"""Run the published research against a private local data root."""
import argparse,os,sys,runpy
from pathlib import Path
def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',required=True);p.add_argument('--stage',choices=['analysis','response','guard','report'],required=True);args=p.parse_args()
    root=Path(args.data_root).resolve();assert (root/'reports/rich_context_20261103/learning_table.parquet').exists()
    os.environ['STRESSLAB_AUDIT_ROOT']=str(root);here=Path(__file__).resolve().parent
    if here.parent.name=='validation':
        for path in sorted(here.parent.iterdir()):
            if path.is_dir():sys.path.append(str(path))
    sys.path.insert(0,str(here));names={'analysis':'analyze_variables_20261104','response':'train_orthogonal_response_20261104','guard':'guard_orthogonal_response_20261104','report':'report_variables_20261104'}
    runpy.run_path(str(here/(names[args.stage]+'.py')),run_name='__main__')
if __name__=='__main__':main()
