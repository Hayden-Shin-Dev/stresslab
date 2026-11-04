import argparse,os,sys,runpy
from pathlib import Path

def main():
    names={'train':'train_selected_response_20261104','diagnosis':'diagnose_selected_response_20261104','air-control':'air_oil_control_20261104','report':'report_selected_response_20261104','followup':'retain_controls_response_20261104','joint-audit':'audit_joint_response_20261104','finalize':'finalize_selected_response_20261104'}
    p=argparse.ArgumentParser();p.add_argument('--data-root',required=True);p.add_argument('--stage',choices=names,required=True);a=p.parse_args()
    root=Path(a.data_root).resolve();assert (root/'reports/rich_context_20261103/learning_table.parquet').exists();os.environ['STRESSLAB_AUDIT_ROOT']=str(root)
    here=Path(__file__).resolve().parent
    for f in sorted(here.parent.iterdir()):
        if f.is_dir():sys.path.append(str(f))
    sys.path.insert(0,str(here));runpy.run_path(str(here/(names[a.stage]+'.py')),run_name='__main__')
if __name__=='__main__':main()
