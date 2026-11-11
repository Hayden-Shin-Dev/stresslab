"""Connection failure tests; all storage and PubSub calls are local mocks."""
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import function_app as app
import live_push as push


class ConnectionRecoveryTests(unittest.TestCase):
    def setUp(self):
        app._read_conn = None
        app._read_retry_after = 0
        app._read_lock = threading.Lock()
        push.client.cache_clear()

    def connection(self):
        conn = Mock(closed=False)
        cursor = Mock()
        cursor.fetchall.return_value = [({'asset_id': '005930', 'price': 101, 'is_mock': False},)]
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_reuses_reader_and_preserves_writer(self):
        conn, cursor = self.connection()
        writer = object()
        with patch.dict(app.os.environ, {'PG_HOST': 'test', 'PG_USER': 'test'}), \
             patch.object(app, '_get_password', return_value='unused'), \
             patch.object(app, 'active_assets', return_value=['005930']), \
             patch.object(app, '_conn', writer), \
             patch.object(app.psycopg, 'connect', return_value=conn) as connect:
            for _ in range(5):
                self.assertEqual(app.read_latest()[0]['price'], 101)
            self.assertIs(app._conn, writer)
            connect.assert_called_once()
            self.assertEqual(cursor.execute.call_count, 5)
            self.assertTrue(connect.call_args.kwargs['autocommit'])
            self.assertEqual(connect.call_args.kwargs['connect_timeout'], 3)

    def test_disconnect_backoff_then_fresh_connection(self):
        broken, cursor = self.connection()
        cursor.execute.side_effect = app.psycopg.OperationalError('disconnected')
        healthy, _ = self.connection()
        app._read_conn = broken
        with patch.object(app.time, 'monotonic', return_value=100), \
             patch.object(app, 'active_assets', return_value=['005930']):
            with self.assertRaises(app.LatestUnavailable):
                app.read_latest()
        broken.close.assert_called_once()
        with patch.object(app.time, 'monotonic', return_value=103), \
             patch.object(app.psycopg, 'connect') as connect:
            with self.assertRaises(app.LatestUnavailable):
                app.read_latest()
            connect.assert_not_called()
        with patch.object(app.time, 'monotonic', return_value=106), \
             patch.dict(app.os.environ, {'PG_HOST': 'test', 'PG_USER': 'test'}), \
             patch.object(app, '_get_password', return_value='unused'), \
             patch.object(app, 'active_assets', return_value=['005930']), \
             patch.object(app.psycopg, 'connect', return_value=healthy):
            self.assertEqual(app.read_latest()[0]['price'], 101)

    def test_storage_failure_is_503_not_empty_success(self):
        with patch.object(app, 'read_latest', side_effect=app.LatestUnavailable()):
            response = app.latest_snapshot(None)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers['Retry-After'], '5')
        self.assertNotIn('quotes', json.loads(response.get_body()))

    def test_parallel_query_does_not_share_transaction(self):
        app._read_lock.acquire()
        try:
            with self.assertRaises(app.LatestUnavailable):
                app.read_latest()
        finally:
            app._read_lock.release()

    def test_pubsub_sdk_applies_bounded_transport(self):
        # Construct the actual SDK client but never send a network request.
        with patch.object(push, 'DefaultAzureCredential', return_value=Mock()):
            client = push.client()
        config = client._client._pipeline._transport.connection_config
        self.assertEqual(config.timeout, 2)
        self.assertEqual(config.read_timeout, 3)
        self.assertEqual(client._config.retry_policy.total_retries, 0)
        client.close()


if __name__ == '__main__':
    unittest.main()
