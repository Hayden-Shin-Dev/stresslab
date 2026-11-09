import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from analyze_effect_atlas_20261104 import OUT,SRC,SHOCKS

def main():
    c=pd.read_parquet(OUT/'coordinates/curves.parquet');names=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str}).drop_duplicates('asset').set_index('asset')['name']
    plt.rcParams['font.family']='Malgun Gothic';plt.rcParams['axes.unicode_minus']=False
    shocks=['환율 변화(%)','미국 금리 변화(bp)','WTI 변화(%)','VIX 변화(포인트)'];outcomes=['return','up_score','crash_score'];ylabs=['중심 수익률 차이(%p)','상승 점수 차이(점)','급락 점수 차이(점)']
    for asset in ['005930','000660','003490','010950','005380']:
        fig,axes=plt.subplots(3,4,figsize=(15,9))
        for i,outcome in enumerate(outcomes):
            for j,shock in enumerate(SHOCKS):
                ax=axes[i,j];z=c[(c.asset==asset)&(c.feature==shock)&(c.outcome==outcome)]
                for year,color in [(2018,'#3274a1'),(2020,'#bd6b31')]:
                    q=z[z.fold==year].sort_values('bin')
                    if len(q):ax.plot((q.low+q.high)/2,q.ale,marker='o',markersize=3,label=f'{year}~{year+1}',color=color)
                ax.axhline(0,color='#aaaaaa',linewidth=.7);ax.grid(alpha=.15);ax.set_xlabel(shocks[j]);ax.set_ylabel(ylabs[i]);ax.spines[['top','right']].set_visible(False)
                if i==0 and j==0:ax.legend(frameon=False)
        fig.suptitle(f'{names[asset]} | 다른 입력을 유지한 국소 모델 반응',fontsize=17)
        fig.text(.05,.018,'각 기간 이전 자료로 학습한 모델의 ALE 곡선입니다. 인과효과와 미래 손익 예측이 아닙니다. 상승·급락 점수는 보정된 확률이 아닙니다.',fontsize=10)
        fig.tight_layout(rect=[0,.05,1,.95]);fig.savefig(OUT/f'response_{asset}.png',dpi=130);plt.close(fig)
if __name__=='__main__':main()
