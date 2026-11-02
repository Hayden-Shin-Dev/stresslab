import sys, unittest, json
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).parent))
from sessions import classify_session
from collector import normalize
from jsonschema import Draft202012Validator, FormatChecker


class SessionsTest(unittest.TestCase):
    def classify(self, clock, code='2', venue='KRX', day='2026-11-02'):
        return classify_session({'20':clock, '290':code, '9081':venue},
            f'{day}T{clock[:2]}:{clock[2:4]}:{clock[4:]}+09:00')

    def test_supported_windows_and_boundaries(self):
        cases=[('083500','1','KRX','afterhours','krx_preopen_closing_price'),
               ('090001','2','KRX','regular','krx_regular'),
               ('151959','2','KRX','regular','krx_regular'),
               ('152000','2','KRX','auction','krx_closing_auction_window'),
               ('153000','2','KRX','auction','krx_closing_auction_window'),
               ('155959','3','KRX','afterhours','krx_postclose_closing_price'),
               ('160000','2','KRX','afterhours','krx_aftermarket'),
               ('161647','2','KRX','afterhours','krx_aftermarket'),
               ('190000','3','KRX','afterhours','krx_aftermarket'),
               ('083000','2','NXT','afterhours','nxt_premarket'),
               ('090030','2','NXT','regular','nxt_mainmarket'),
               ('161647','2','NXT','afterhours','nxt_aftermarket')]
        for clock,code,venue,session,detail in cases:
            with self.subTest(clock=clock,venue=venue):
                got=self.classify(clock,code,venue)
                self.assertEqual((got['session'],got['session_detail']),(session,detail))

    def test_old_single_price_market_is_date_bounded(self):
        self.assertEqual(self.classify('161000','3',day='2026-09-11')['session_detail'],'krx_legacy_afterhours_call_auction')
        self.assertEqual(self.classify('161000','3',day='2026-09-14')['session_detail'],'krx_aftermarket')

    def test_unknown_has_a_reason(self):
        for args in [('161647','1','KRX'),('210000','2','KRX'),('120000','9','KRX'),('120000','2','UNKNOWN')]:
            with self.subTest(args=args):
                result=self.classify(*args)
                self.assertEqual(result['session'],'unknown')
                self.assertTrue(result['session_reason'])
        self.assertEqual(classify_session({'9081':'KRX','290':'2'},None)['session'],'unknown')
        self.assertEqual(self.classify('120000',day='2026-11-01')['session'],'unknown')

    def test_delayed_receipt_does_not_change_trade_session(self):
        row={'type':'0B','item':'005930','values':{'20':'145959','290':'2','9081':'KRX','10':'+70000','13':'1000','15':'-10'}}
        event=normalize(row,datetime(2026,11,2,7,0,tzinfo=timezone.utc))
        self.assertEqual(event['session'],'regular')
        self.assertEqual(event['trade_volume'],10)
        self.assertEqual(event['event_time'],'2026-11-02T05:59:59Z')
        schema=json.loads((Path(__file__).parents[2]/'contracts/realtime/schema.json').read_text(encoding='utf8'))
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(event)


if __name__=='__main__':unittest.main()
