from pathlib import Path
import os,json

ROOT = Path(__file__).resolve().parents[1]
# Data, model and evidence directories always move as one verified release.
_release=ROOT
_pointer=ROOT/'active_release.json'
if _pointer.exists() and not os.environ.get('STRESSLAB_DATA_DIR'):
    _release=Path(json.loads(_pointer.read_text(encoding='utf-8'))['release_path']).resolve()
    _allowed=(ROOT/'.local'/'releases').resolve()
    if not _release.is_relative_to(_allowed):raise RuntimeError('Active release is outside the managed release directory')
DATA = Path(os.environ.get('STRESSLAB_DATA_DIR',str(_release/'data')))
MODELS = Path(os.environ.get('STRESSLAB_MODEL_DIR',str(_release/'models')))
REPORTS = Path(os.environ.get('STRESSLAB_REPORT_DIR',str(_release/'reports')))
HORIZONS = [1, 5, 20, 60]
SEED = 20261018
ASSETS = {
    'kospi': {'name':'KOSPI','symbol':'KOSPI','kind':'index','sector':'시장'},
    'kosdaq': {'name':'KOSDAQ','symbol':'KOSDAQ','kind':'index','sector':'시장'},
    'samsung': {'name':'삼성전자','symbol':'005930','kind':'stock','sector':'반도체'},
    'hyundai': {'name':'현대자동차','symbol':'005380','kind':'stock','sector':'자동차'},
    'shinhan': {'name':'신한지주','symbol':'055550','kind':'stock','sector':'금융'},
    'semis': {'name':'KODEX 반도체','symbol':'091160','kind':'sector_etf','sector':'반도체'},
    'banks': {'name':'KODEX 은행','symbol':'091170','kind':'sector_etf','sector':'금융'},
}
SHOCKS = {
    'usdkrw': {'name':'원/달러 (뉴욕 관측)','unit':'%','kind':'relative','fred':'DEXKOUS','level_unit':'KRW/USD'},
    'us_treasury_10y': {'name':'미국 국채 10년','unit':'bp','kind':'bp','fred':'DGS10','level_unit':'%'},
    'wti': {'name':'WTI 현물 · Cushing','unit':'%','kind':'relative','fred':'DCOILWTICO','level_unit':'USD/배럴'},
    'vix': {'name':'VIX','unit':'pt','kind':'points','fred':'VIXCLS','level_unit':'pt'},
}
# Domestic 3-year and S&P data remain in audit, but are not spliced into this consistent panel.
STATES = ['kospi_vol20','kospi_trend20','vix_level','us_yield_level','fx_trend20','oil_level']
EVENTS = [
    {'id':'gfc','name':'글로벌 금융위기','start':'2008-09-12','end':'2008-11-20'},
    {'id':'covid','name':'코로나19 급락','start':'2020-02-19','end':'2020-03-19'},
    {'id':'tightening','name':'2022 금리 인상·강달러','start':'2022-08-16','end':'2022-09-30'},
    {'id':'aug2024','name':'2024년 8월 변동성 확대','start':'2024-07-31','end':'2024-08-05'},
]
