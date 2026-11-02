"""Synthetic unit cases; never ingestion data. Run with unittest discovery."""
import unittest
import pandas as pd
from price_bridge_reference import validate_connection


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame([dict(asset_id='005930', date='2026-10-16', close=100, volume=10)])
        self.rows = [dict(ISU_CD='005930', BAS_DD='20261016', TDD_CLSPRC='100', CMPPREVDD_PRC='0', FLUC_RT='0', ACC_TRDVOL='10'),
                     dict(ISU_CD='005930', BAS_DD='20261019', TDD_CLSPRC='102', CMPPREVDD_PRC='2', FLUC_RT='2', ACC_TRDVOL='12')]

    def check_rows(self, rows):
        return validate_connection(self.history, rows, ['005930'], ['2026-10-16', '2026-10-19'], raw_comparable_from='2026-10-16')

    def test_connection_and_repeat(self):
        report, new = self.check_rows(self.rows)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(len(new), 1)
        self.history = pd.concat([self.history, new], ignore_index=True)
        report, new = self.check_rows(self.rows)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(len(new), 0)

    def test_action_blocks_all_output(self):
        self.rows[1]['CMPPREVDD_PRC'] = '12'
        report, new = self.check_rows(self.rows)
        self.assertIn('official_adjustment_required', [e['reason'] for e in report['errors']])
        self.assertTrue(new.empty)

    def test_missing_boundary(self):
        report, new = self.check_rows(self.rows[1:])
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(new.empty)

    def test_duplicate(self):
        report, new = self.check_rows(self.rows + [self.rows[1]])
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(new.empty)

    def test_return_mismatch(self):
        self.rows[1]['FLUC_RT'] = '20'
        report, new = self.check_rows(self.rows)
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(new.empty)


if __name__ == '__main__':
    unittest.main()
