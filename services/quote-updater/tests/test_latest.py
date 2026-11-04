"""Local only: no fabricated messages are sent to Azure."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import live_push as push
import function_app as app

class LatestTests(unittest.TestCase):
    def setUp(self):
        push._sent.clear();push._last_send=-float('inf')
    def q(self,price=100):
        return dict(asset_id='005930',price=price,is_mock=False,event_id=str(price))
    def test_coalesced_delivery_retry_and_idle(self):
        sender=Mock()
        with patch.object(push,'client',return_value=sender),patch.object(push.time,'monotonic',return_value=10):
            self.assertEqual(push.publish_latest([self.q()]),1)
            self.assertEqual(push.publish_latest([self.q(101)]),0)
        with patch.object(push,'client',return_value=sender),patch.object(push.time,'monotonic',return_value=11.1):
            self.assertEqual(push.publish_latest([self.q(105)]),1)
            self.assertEqual(sender.send_to_all.call_args.kwargs['message']['quotes'][0]['price'],105)
        with patch.object(push,'client',return_value=sender),patch.object(push.time,'monotonic',return_value=13):
            self.assertEqual(push.publish_latest([self.q(105)]),0)
            sender.send_to_all.side_effect=RuntimeError('send failed')
            with self.assertRaises(RuntimeError):push.publish_latest([self.q(106)])
            sender.send_to_all.side_effect=None
            self.assertEqual(push.publish_latest([self.q(106)]),1)
    def test_out_of_order_batch_uses_trade_time(self):
        import json
        q=dict(record_type='quote_event',asset_id='005930',price=100,received_at='2026-11-04T04:00:02Z',event_time='2026-11-04T04:00:01Z',is_mock=False)
        older={**q,'price':90,'event_time':'2026-11-04T04:00:00Z','received_at':'2026-11-04T04:00:03Z'}
        rows,skipped=app.latest_per_asset([json.dumps(q),json.dumps(older)])
        self.assertEqual(rows[0][1],100);self.assertEqual(skipped,0)
    def test_snapshot_without_trade_wait(self):
        import json
        with patch.object(app,'read_latest',return_value=[self.q()]):
            response=app.latest_snapshot(None)
            self.assertEqual(json.loads(response.get_body())['quotes'][0]['price'],100)
    def test_writer_has_no_pubsub_call(self):
        import inspect
        self.assertNotIn('publish_',inspect.getsource(next(f for f in app.app.get_functions() if f.get_function_name()=='eh_to_pg').get_user_function()))

if __name__=='__main__':unittest.main()

