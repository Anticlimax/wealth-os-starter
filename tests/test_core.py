import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from wealthos.core import append_event, effective_events, load, number, project, read_inputs, scenario, timestamp, validate

ROOT = Path(__file__).resolve().parents[1]
AT = '2026-02-01T12:00:00+08:00'


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'ledger'
        shutil.copytree(ROOT / 'examples/demo', self.root)
        self.data = read_inputs(self.root)

    def snap(self):
        return project(self.data, AT)

    def trade(self):
        return load(ROOT / 'examples/events/trade.json')

    def test_demo_reconciles(self):
        s = self.snap()
        self.assertEqual((s['total_assets'], s['total_liabilities'], s['net_worth']), (105000, 15000, 90000))
        self.assertEqual(s['cashflow']['monthly_surplus'], 5000)
        self.assertEqual(s['emergency']['available'], 45000)
        self.assertEqual(s['emergency']['target'], 42000)
        self.assertEqual(s['plan']['goals_monthly_required'], 2000)
        self.assertEqual(s['plan']['goal_surplus_after_contributions'], 3000)
        self.assertEqual(s['pending_events'], 1)

    def test_missing_fx_does_not_become_zero(self):
        self.data['prices']['fx'] = {}
        s = self.snap()
        self.assertIsNone(s['total_assets'])
        self.assertIsNone(s['net_worth'])
        self.assertEqual(s['known_assets'], 70000)
        self.assertIsNone(s['plan']['allocation'][0]['actual_percent'])

    def test_missing_debt_price_keeps_assets_but_not_net(self):
        del self.data['prices']['quotes']['DEMO-DEBT']
        s = self.snap()
        self.assertEqual(s['total_assets'], 105000)
        self.assertIsNone(s['total_liabilities'])
        self.assertIsNone(s['net_worth'])

    def test_future_price_unavailable(self):
        self.data['prices']['quotes']['DEMO-EQUITY']['as_of'] = '2027-01-01T00:00:00Z'
        self.assertIsNone(self.snap()['total_assets'])

    def test_missing_reserve_input(self):
        self.data['profile']['monthly_expenses'] = None
        s = self.snap()
        self.assertIsNone(s['cashflow']['monthly_surplus'])
        self.assertIsNone(s['emergency']['gap'])

    def test_trade_cash_and_fee(self):
        self.data['events'].append(self.trade())
        s = self.snap()
        self.assertEqual(s['total_assets'], 104998)
        self.assertEqual(s['emergency']['available'], 43998)

    def test_pending_subscription_then_settlement_no_double_debit(self):
        self.data['events'].append(load(ROOT / 'examples/events/subscription.json'))
        s = self.snap()
        self.assertEqual(s['total_assets'], 105000)
        self.assertEqual(s['emergency']['available'], 44000)
        self.assertEqual(next(p['quantity'] for p in s['positions'] if p['asset'] == 'PENDING-CNY'), 1000)
        self.data['events'].append(load(ROOT / 'examples/events/settlement.json'))
        settled = self.snap()
        self.assertEqual(settled['total_assets'], 105000)
        self.assertEqual(settled['emergency']['available'], 44000)
        self.assertNotIn('PENDING-CNY', [p['asset'] for p in settled['positions']])

    def test_pending_has_no_effect(self):
        before = self.snap()['net_worth']
        self.data['events'][-1]['legs'][0]['quantity_delta'] = 999999
        self.assertEqual(self.snap()['net_worth'], before)

    def test_correction_replaces_all_old_legs(self):
        event = copy.deepcopy(self.data['events'][0])
        event.update(id='demo-correction', supersedes=event['id'])
        event['legs'][0]['quantity_delta'] = 13000
        self.data['events'].append(event)
        self.assertEqual(self.snap()['net_worth'], 91000)
        self.assertEqual(len(self.data['events']), 4)

    def test_confirm_pending_via_new_version(self):
        event = copy.deepcopy(self.data['events'][-1])
        event.update(id='demo-confirmation', supersedes=event['id'], status='confirmed')
        self.data['events'].append(event)
        s = self.snap()
        self.assertEqual(s['net_worth'], 91000)
        self.assertEqual(s['pending_events'], 0)

    def test_duplicate_evidence_rejected(self):
        event = copy.deepcopy(self.data['events'][0]); event['id'] = 'duplicate'
        self.data['events'].append(event)
        with self.assertRaises(ValueError): self.snap()

    def test_duplicate_id_rejected(self):
        self.data['events'].append(self.data['events'][0])
        with self.assertRaises(ValueError): self.snap()

    def test_future_event_does_not_affect_current(self):
        self.data['events'][0]['occurred_at'] = '2027-01-01T00:00:00Z'
        self.data['events'][0]['recorded_at'] = '2027-01-01T00:00:00Z'
        self.assertEqual(self.snap()['total_assets'], 93000)

    def test_preopening_event_rejected(self):
        self.data['events'][0]['occurred_at'] = self.data['opening']['as_of']
        with self.assertRaises(ValueError): self.snap()

    def test_recording_before_occurrence_rejected(self):
        self.data['events'][0]['recorded_at'] = '2025-01-01T00:00:00Z'
        with self.assertRaises(ValueError): self.snap()

    def test_unknown_position_rejected(self):
        self.data['events'][0]['legs'][0]['account'] = 'unknown'
        with self.assertRaises(ValueError): self.snap()

    def test_negative_position_rejected(self):
        self.data['events'][1]['legs'][0]['quantity_delta'] = -999999
        with self.assertRaises(ValueError): self.snap()

    def test_unbalanced_transfer_rejected(self):
        event = self.trade(); event['kind'] = 'transfer'
        self.data['events'].append(event)
        with self.assertRaises(ValueError): self.snap()

    def test_trade_requires_cash_or_outgoing_leg(self):
        event = self.trade(); event['legs'] = event['legs'][1:]
        self.data['events'].append(event)
        with self.assertRaises(ValueError): self.snap()

    def test_idempotent_append_and_conflict(self):
        event = self.trade()
        self.assertTrue(append_event(self.root, event, True)['appended'])
        self.assertFalse(append_event(self.root, event, True)['appended'])
        event['note'] = 'changed'
        with self.assertRaises(ValueError): append_event(self.root, event, True)
        self.assertEqual(len(read_inputs(self.root)['events']), 4)

    def test_confirmation_required(self):
        with self.assertRaises(ValueError): append_event(self.root, self.trade())
        self.assertEqual(len(read_inputs(self.root)['events']), 3)

    def test_append_validates_intermediate_negative_balances(self):
        event = self.trade(); event['legs'][0]['quantity_delta'] = -50000
        with self.assertRaises(ValueError): append_event(self.root, event, True)
        self.assertEqual(len(read_inputs(self.root)['events']), 3)

    def test_writer_lock_prevents_append(self):
        (self.root / '.write.lock').touch()
        with self.assertRaises(ValueError): append_event(self.root, self.trade(), True)
        self.assertTrue((self.root / '.write.lock').exists())

    def test_zero_is_not_missing(self):
        self.data['profile']['monthly_income'] = 0
        self.assertEqual(self.snap()['cashflow']['monthly_surplus'], -7000)

    def test_target_sum_and_numeric_validation(self):
        self.data['plan']['targets']['现金'] = 36
        with self.assertRaises(ValueError): self.snap()
        for bad in (None, True, 'NaN', 'Infinity', '-Infinity', 'abc'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): number(bad)
        with self.assertRaises(ValueError): timestamp('2026-01-01')

    def test_unconfirmed_empty_is_unknown(self):
        self.data['opening'].update(confirmed=False, positions=[])
        self.data['events'] = []
        s = self.snap()
        self.assertIsNone(s['net_worth'])
        self.assertIsNone(s['emergency']['available'])

    def test_plan_never_changes_positions(self):
        before = self.snap()['positions']
        self.data['plan']['status'] = 'confirmed'
        self.data['plan']['targets'] = {'股票': 100}
        self.assertEqual(before, self.snap()['positions'])

    def test_future_confirmation_keeps_pending_visible(self):
        event = copy.deepcopy(self.data['events'][-1])
        event.update(id='future-confirmation', supersedes=event['id'], status='confirmed',
                     occurred_at='2027-01-01T00:00:00Z', recorded_at='2027-01-01T00:00:00Z')
        self.data['events'].append(event)
        self.assertEqual(self.snap()['pending_events'], 1)
        self.assertEqual(self.snap()['net_worth'], 90000)

    def test_scenario_zero_negative_and_bounds(self):
        self.assertEqual(scenario(100000, 2000, 0, 10)['years'][-1]['balance'], 340000)
        self.assertGreater(scenario(100000, 2000, 100, 80)['years'][-1]['balance'], 1e20)
        self.assertLess(scenario(100000, 0, -10, 1)['years'][-1]['balance'], 100000)
        for args in ((-1, 0, 0, 1), (1, 0, -100, 1), (1, 0, 1, 0)):
            with self.assertRaises(ValueError): scenario(*args)


if __name__ == '__main__': unittest.main()
