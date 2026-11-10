"""Run: python -m unittest discover -s fabric/batch/quality -p test_publication_evidence.py"""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from publication_evidence import fred_records, load_ledger, select_evidence, write_json, COLUMNS, fx_observed_at, exact_publication_for_values, attach_bok_notice_times, OfficialTables


class EvidenceTests(unittest.TestCase):
    def test_official_table_without_optional_parser(self):
        text='<table><tr><th>COUNTRY</th><th><b>Oct. 26</b></th></tr><tr><td>SOUTH KOREA</td><td>1,300 &amp; note</td></tr></table>'
        self.assertEqual(OfficialTables(text).tables,[[['COUNTRY','Oct. 26'],['SOUTH KOREA','1,300 & note']]])

    def records(self):
        return fred_records('usdkrw', {'observations': [
            {'date':'2020-01-02','value':'1100','realtime_start':'2020-01-03','realtime_end':'2020-01-07'},
            {'date':'2020-01-02','value':'1101','realtime_start':'2020-01-08','realtime_end':'9999-12-31'}]}, 'raw', 'hash')

    def ledger(self):
        f = pd.DataFrame(self.records(), columns=COLUMNS)
        f.observation_date = pd.to_datetime(f.observation_date)
        for c in ['known_by','valid_until','publication_at']: f[c]=pd.to_datetime(f[c],utc=True)
        return f

    def test_no_invented_clock(self):
        r=self.records()[0]
        self.assertIsNone(r['publication_at'])
        self.assertEqual(pd.Timestamp(r['known_by']),pd.Timestamp('2020-01-04T12:00Z'))

    def test_future_revision_and_wrong_value_rejected(self):
        rows=pd.DataFrame({'trading_date':pd.to_datetime(['2020-01-03','2020-01-06','2020-01-06','2020-01-10','2020-01-10']),
            'observation_date':pd.to_datetime(['2020-01-02']*5),'value':[1100.,1100.,1101.,1100.,1101.]})
        selected=select_evidence(rows,self.ledger(),'usdkrw')
        self.assertEqual(selected.known_by.notna().tolist(),[False,True,False,False,True])

    def test_other_source_rejected(self):
        rows=pd.DataFrame({'trading_date':pd.to_datetime(['2020-01-06']), 'observation_date':pd.to_datetime(['2020-01-02']),'value':[1100.]})
        self.assertTrue(select_evidence(rows,self.ledger(),'wti').known_by.isna().all())

    def test_hash_guard_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=root/'fred/publication/raw.json';raw.parent.mkdir(parents=True);raw.write_bytes(b'{}')
            digest=hashlib.sha256(raw.read_bytes()).hexdigest()
            record=self.records()[0];record.update(source_ref='Files/bronze/fred/publication/raw.json',evidence_sha256=digest)
            for run in ['a','b']:
                p=root/'_publication'/run;write_json(p/'records.json',[record])
                write_json(p/'manifest.json',{'records_file':f'_publication/{run}/records.json','records_sha256':hashlib.sha256((p/'records.json').read_bytes()).hexdigest(), 'files':[{'file':'fred/publication/raw.json','sha256':digest}]})
            self.assertEqual(len(load_ledger(root)),1)
            raw.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'evidence_hash_mismatch'):load_ledger(root)

    def test_official_noon_definition_handles_dst(self):
        metadata={'seriess':[{'id':'DEXKOUS','notes':'Noon buying rates in New York City'}]}
        result=fx_observed_at(pd.Series(pd.to_datetime(['2020-01-03','2020-07-03'])),metadata)
        self.assertEqual(result.dt.hour.tolist(),[17,16])
        with self.assertRaises(ValueError):fx_observed_at(pd.Series(pd.to_datetime(['2020-01-03'])),{'seriess':[{'id':'DEXKOUS','notes':''}]})

    def test_date_bound_never_becomes_exact_publication(self):
        rows=pd.DataFrame({'observation_date':pd.to_datetime(['2020-01-02']),'value':[1100.]})
        self.assertTrue(exact_publication_for_values(rows,self.ledger(),'usdkrw').isna().all())

    def test_bok_rss_requires_same_article_and_registered_date(self):
        rss=b'<rss><channel><item><link>https://www.bok.or.kr/?nttId=123</link><pubDate>Mon, 09 Nov 2026 11:00:00 +0900</pubDate></item></channel></rss>'
        base=dict(source='korea_3y',source_ref='Files/bronze/ecos/publication/run/bok_123.html',known_by='2026-11-10T00:00:00+09:00',observation_date='2026-11-06',publication_at=None)
        rows=[base.copy(),{**base,'source_ref':'Files/bronze/ecos/publication/run/bok_124.html'},{**base,'known_by':'2026-11-11T00:00:00+09:00'}]
        attach_bok_notice_times(rows,rss,'rss','hash')
        self.assertEqual(pd.Timestamp(rows[0]['publication_at']),pd.Timestamp('2026-11-09T02:00Z'))
        self.assertIsNone(rows[1]['publication_at']);self.assertIsNone(rows[2]['publication_at'])


if __name__=='__main__': unittest.main()
