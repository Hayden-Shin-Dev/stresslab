import argparse,os,sys,runpy
from pathlib import Path

def main():
    names={'analysis':'crash_mechanism_20261104','interactions':'analyze_all_interactions_20261104','train':'crash_mechanism_20261104','apply':'apply_crash_analysis_20261104','report':'report_crash_mechanism_20261104'}
    p=argparse.ArgumentParser();p.add_argument('--data-root',required=True);p.add_argument('--stage',choices=names,required=True);a=p.parse_args()
    root=Path(a.data_root).resolve();assert (root/'reports/rich_context_20261103/learning_table.parquet').exists();os.environ['STRESSLAB_AUDIT_ROOT']=str(root)
    here=Path(__file__).resolve().parent
    for f in sorted(here.parent.iterdir()):
        if f.is_dir():sys.path.append(str(f))
    sys.path.insert(0,str(here));path=here/(names[a.stage]+'.py');sys.argv=[str(path)]+([a.stage] if a.stage in ['analysis','train'] else []);runpy.run_path(str(path),run_name='__main__')
if __name__=='__main__':main()
