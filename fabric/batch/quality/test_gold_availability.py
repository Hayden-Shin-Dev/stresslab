"""Leakage boundary tests for the shared local/Fabric Gold selector."""
import unittest
import pandas as pd
from gold_availability import select_asof, validate_gold_provenance, SOURCES


def event(value=100., known='2026-11-02T06:29:00Z', until=None, exact=None):
    return dict(source='wti', observation_date='2026-10-30', value=value,
                known_by=known, valid_until=until, publication_at=exact,
                availability_basis='fred_vintage_date_conservative_upper_bound',
                source_ref='Files/bronze/test.json', evidence_sha256='a'*64)


class AvailabilityTests(unittest.TestCase):
    def pick(self, *events, day='2026-11-02'):
        return select_asof([day], pd.DataFrame(events), 'wti').iloc[0]

    def test_future_publication_is_excluded(self):
        r = self.pick(event(known='2026-11-02T06:31:00Z'))
        self.assertFalse(r.verified)
        self.assertTrue(pd.isna(r.value))

    def test_boundary_and_date_only_do_not_create_clock(self):
        r = self.pick(event(known='2026-11-02T06:30:00Z'))
        self.assertTrue(r.verified)
        self.assertTrue(pd.isna(r.publication_at))
        self.assertEqual(r.evidence_precision, 'conservative_date_bound')

    def test_exact_clock_is_preserved(self):
        r = self.pick(event(exact='2026-11-02T06:28:00Z'))
        self.assertEqual(r.publication_at, pd.Timestamp('2026-11-02T06:28:00Z'))

    def test_revision_cannot_leak_back(self):
        old = event(100., until='2026-11-03T00:00:00Z')
        new = event(900., known='2026-11-04T00:00:00Z')
        self.assertEqual(self.pick(old,new).value,100.)
        self.assertFalse(self.pick(old,new,day='2026-11-03').verified)
        self.assertEqual(self.pick(old,new,day='2026-11-04').value,900.)

    def test_earlier_observation_selected_before_new_release(self):
        early = event()
        later = event(900.,known='2026-11-03T00:00:00Z')
        later['observation_date']='2026-11-01'
        self.assertEqual(self.pick(early,later).value,100.)

    def test_expired_or_stale_is_not_used(self):
        self.assertFalse(self.pick(event(until='2026-11-02T06:30:00Z')).verified)
        self.assertFalse(self.pick(event(),day='2026-12-01').verified)

    def test_conflicting_values_fail_closed(self):
        self.assertEqual(self.pick(event(),event(200.)).timing_status,'conflicting_vintage_values')

    def test_future_observation_rejected(self):
        e=event();e['observation_date']='2026-11-02'
        self.assertFalse(self.pick(e).verified)

    def test_unknown_basis_rejected(self):
        e=event();e['availability_basis']='guessed_clock'
        with self.assertRaises(ValueError):self.pick(e)

    def test_value_tampering_detected(self):
        rows=[];g={'trading_date':['2026-11-02']}
        for source in SOURCES:
            e=event();e['source']=source
            p=select_asof(g['trading_date'],pd.DataFrame([e]),source);rows.append(p)
            g[source]=p.value;g[source+'_observation_date']=p.observation_date;g[source+'_available_at']=p.publication_at
        gold=pd.DataFrame(g);provenance=pd.concat(rows,ignore_index=True)
        validate_gold_provenance(gold,provenance)
        gold['wti']=900.
        with self.assertRaises(ValueError):validate_gold_provenance(gold,provenance)


if __name__=='__main__':unittest.main()
