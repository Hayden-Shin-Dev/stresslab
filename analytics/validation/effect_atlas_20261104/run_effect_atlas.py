import argparse,os,sys,runpy
from pathlib import Path

def main():
    names={'audit':'audit_effect_identities_20261104','analysis':'analyze_effect_atlas_20261104','coordinates':'analyze_coordinate_effects_20261104','balance':'balance_effect_atlas_20261104','apply':'apply_effect_atlas_20261104','report':'report_effect_atlas_20261104','plot':'plot_effect_atlas_20261104','cases':'explain_effect_cases_20261104','summary':'summarize_effect_application_20261104'}
    p=argparse.ArgumentParser();p.add_argument('--data-root',required=True);p.add_argument('--stage',choices=names,required=True);a=p.parse_args()
    root=Path(a.data_root).resolve();assert (root/'reports/rich_context_20261103/learning_table.parquet').exists();os.environ['STRESSLAB_AUDIT_ROOT']=str(root)
    here=Path(__file__).resolve().parent
    if here.parent.name=='validation':
        for f in sorted(here.parent.iterdir()):
            if f.is_dir():sys.path.append(str(f))
    sys.path.insert(0,str(here));runpy.run_path(str(here/(names[a.stage]+'.py')),run_name='__main__')
if __name__=='__main__':main()
