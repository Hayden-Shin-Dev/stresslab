"""공표 근거와 가격 연결의 실패 조건을 검증합니다."""
# 2026-11-09 12:54 KST 민철 추가 — 미래 자료/오래된 자료/기업행사 불일치 차단 테스트.
import unittest
import ast
from pathlib import Path
import pandas as pd
from batch_evidence import macro_curve, price_metadata


class EvidenceTests(unittest.TestCase):
    # 2026-11-09 13:08 KST 민철 추가 — 새 기업행사로 연결이 끊기면 기존 Gold를 덮어쓰지 않는지 확인합니다.
    def test_gold_price_gate_blocks_unverified_quarantine(self):
        source=(Path(__file__).resolve().parents[1]/'notebooks/nb_03_Gold_Build.py').read_text(encoding='utf8')
        fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='require_verified_price_basis')
        namespace={}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'gold_price_gate','exec'),namespace)
        check=namespace['require_verified_price_basis']
        good=pd.DataFrame([dict(price_basis='adjusted',adjustment_version='verified')])
        check(good)
        unknown=pd.DataFrame([dict(price_basis='unknown',adjustment_version=None,quality_status='quarantined')])
        with self.assertRaises(RuntimeError):check(pd.concat([good,unknown],ignore_index=True))

    def test_future_receipt_and_expiry(self):
        ref=pd.DataFrame([dict(date=pd.Timestamp('2020-01-01'),source='usdkrw',value=100.,
            observation_date=pd.Timestamp('2019-12-31'),known_by=pd.Timestamp('2020-01-01',tz='UTC'),source_ref='test',verified=True)])
        files={'fred/api/test/observations/usdkrw.json':('test',dict(retrieved_at='2020-01-05T00:00:00Z',
            rows=[{'date':'2020-01-02','value':'999'}]))}
        out=macro_curve(pd.to_datetime(['2020-01-02','2020-01-06','2020-01-20']),ref,files)
        q=out[out.source.eq('usdkrw')]
        self.assertEqual(q.value.iloc[:2].tolist(),[100.,999.])
        self.assertFalse(q.verified.iloc[-1])
        self.assertTrue(pd.isna(q.value.iloc[-1]))

    def test_official_price_reference_break(self):
        ref=pd.DataFrame([dict(asset_id='005930',trading_date='2020-01-01',close=100.,volume=10,
            quality_status='valid',price_basis='adjusted',adjustment_version='test')])
        stocks=pd.concat([ref,pd.DataFrame([dict(asset_id='005930',trading_date='2020-01-02',close=50.,volume=10,quality_status='valid')])],ignore_index=True)
        files={'krx/api/test/stocks/20200102.json':('test',{'rows':[dict(ISU_CD='005930',BAS_DD='20200102',
            TDD_CLSPRC='50',ACC_TRDVOL='10',CMPPREVDD_PRC='0',FLUC_RT='0')]})}
        meta,issues=price_metadata(stocks,ref,files)
        self.assertEqual(meta.quality_status.iloc[-1],'quarantined')
        self.assertEqual(issues[0]['reason'],'corporate_action_or_price_mismatch')

    def test_historical_value_cannot_be_replaced_by_later_revision(self):
        ref=pd.DataFrame([dict(date=pd.Timestamp('2020-01-02'),source='usdkrw',value=100.,
            observation_date=pd.Timestamp('2020-01-01'),known_by=pd.Timestamp('2020-01-02',tz='UTC'),source_ref='test',verified=True)])
        files={'fred/api/test/observations/usdkrw.json':('test',dict(retrieved_at='2020-01-06T00:00:00Z',
            rows=[{'date':'2020-01-01','value':'200'}]))}
        out=macro_curve([pd.Timestamp('2020-01-02')],ref,files)
        self.assertEqual(out[out.source.eq('usdkrw')].value.iloc[0],100.)

if __name__=='__main__':unittest.main()
