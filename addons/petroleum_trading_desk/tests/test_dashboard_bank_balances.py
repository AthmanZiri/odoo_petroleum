from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestDashboardBankBalances(AccountTestInvoicingCommon):
    """Overview lists live Bank/Cash GL balances, ignoring the date filter."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.misc = cls.company_data['default_journal_misc']
        cls.revenue = cls.company_data['default_account_revenue']
        cls.bank_account = cls.env['account.account'].create({
            'name': 'Desk Test Equity',
            'code': 'BNKDSK1',
            'account_type': 'asset_cash',
            'company_ids': cls.env.company.ids,
        })
        cls.bank_journal = cls.env['account.journal'].search([
            ('default_account_id', '=', cls.bank_account.id),
            ('type', 'in', ('bank', 'cash')),
        ], limit=1)
        cls.cash_account = cls.env['account.account'].create({
            'name': 'Desk Test Petty Cash',
            'code': 'CSHDSK1',
            'account_type': 'asset_cash',
            'company_ids': cls.env.company.ids,
        })
        cls.cash_journal = cls.env['account.journal'].search([
            ('default_account_id', '=', cls.cash_account.id),
        ], limit=1)
        if not cls.bank_journal or not cls.cash_journal:
            raise AssertionError(
                'Bank and Cash GLs must get a Bank/Cash journal')

    def _row(self, data, journal):
        return next(
            (row for row in data['banks']['journals'] if row['id'] == journal.id),
            None)

    def _post_liquidity(self, account, amount):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc.id,
            'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {
                    'name': 'Desk bank deposit',
                    'account_id': account.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Desk bank deposit',
                    'account_id': self.revenue.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def test_zero_balance_bank_is_still_listed(self):
        data = self.env['petroleum.desk.dashboard'].get_dashboard_data()
        row = self._row(data, self.bank_journal)
        self.assertTrue(row, 'Bank journal with a cash book must appear')
        self.assertEqual(row['balance_raw'], 0.0)
        self.assertEqual(row['type'], 'bank')
        cash_row = self._row(data, self.cash_journal)
        self.assertEqual(cash_row['type'], 'cash')
        self.assertEqual(cash_row['balance_raw'], 0.0)

    def test_posted_liquidity_shows_as_current_balance(self):
        self._post_liquidity(self.bank_account, 1500.0)
        self._post_liquidity(self.cash_account, 250.0)
        data = self.env['petroleum.desk.dashboard'].get_dashboard_data()
        self.assertEqual(self._row(data, self.bank_journal)['balance_raw'], 1500.0)
        self.assertEqual(self._row(data, self.cash_journal)['balance_raw'], 250.0)
        self.assertAlmostEqual(
            data['banks']['total_raw'],
            sum(row['balance_raw'] for row in data['banks']['journals']),
            places=2,
        )

    def test_bank_balances_ignore_the_dashboard_date_filter(self):
        self._post_liquidity(self.bank_account, 800.0)
        today = fields.Date.today()
        last_year = today - timedelta(days=365)
        dashboard = self.env['petroleum.desk.dashboard']
        this_window = dashboard.get_dashboard_data({
            'date_from': today.isoformat(),
            'date_to': today.isoformat(),
        })
        old_window = dashboard.get_dashboard_data({
            'date_from': last_year.isoformat(),
            'date_to': last_year.isoformat(),
        })
        self.assertEqual(
            self._row(this_window, self.bank_journal)['balance_raw'],
            self._row(old_window, self.bank_journal)['balance_raw'])
        self.assertEqual(self._row(this_window, self.bank_journal)['balance_raw'], 800.0)

    def test_open_bank_journal_returns_an_action(self):
        action = self.env['petroleum.desk.dashboard'].action_open_bank_journal(
            self.bank_journal.id)
        self.assertTrue(action)
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertFalse(
            self.env['petroleum.desk.dashboard'].action_open_bank_journal(0))
