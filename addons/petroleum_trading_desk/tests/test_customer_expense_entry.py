from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestCustomerExpenseEntry(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Debtor Customer',
            'customer_rank': 1,
        })
        cls.expense = cls.company_data['default_account_expense']
        cls.receivable = cls.company_data['default_account_receivable']
        cls.misc = cls.company_data['default_journal_misc']

    def _wizard(self, **vals):
        defaults = {
            'partner_id': self.customer.id,
            'expense_account_id': self.expense.id,
            'receivable_account_id': self.receivable.id,
            'journal_id': self.misc.id,
            'company_id': self.env.company.id,
            'amount': 1500.0,
            'entry_date': fields.Date.today(),
            'direction': 'absorb',
        }
        defaults.update(vals)
        return self.env['petroleum.desk.customer.expense'].create(defaults)

    def test_absorb_debits_expense_credits_debtor(self):
        action = self._wizard().action_confirm()
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.move_type, 'entry')
        expense_line = move.line_ids.filtered(
            lambda l: l.account_id == self.expense)
        debtor_line = move.line_ids.filtered(
            lambda l: l.account_id == self.receivable)
        self.assertEqual(expense_line.debit, 1500.0)
        self.assertEqual(debtor_line.credit, 1500.0)
        self.assertEqual(debtor_line.partner_id, self.customer)

    def test_charge_debits_debtor_credits_expense(self):
        action = self._wizard(direction='charge', amount=800.0).action_confirm()
        move = self.env['account.move'].browse(action['res_id'])
        expense_line = move.line_ids.filtered(
            lambda l: l.account_id == self.expense)
        debtor_line = move.line_ids.filtered(
            lambda l: l.account_id == self.receivable)
        self.assertEqual(debtor_line.debit, 800.0)
        self.assertEqual(expense_line.credit, 800.0)
        self.assertEqual(debtor_line.partner_id, self.customer)

    def test_zero_amount_refused(self):
        with self.assertRaises(UserError):
            self._wizard(amount=0.0).action_confirm()

    def test_draft_expense_debtor_without_partner_warns(self):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc.id,
            'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {
                    'name': 'No partner',
                    'account_id': self.expense.id,
                    'debit': 100.0,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'No partner',
                    'account_id': self.receivable.id,
                    'debit': 0.0,
                    'credit': 100.0,
                }),
            ],
        })
        self.assertTrue(move.petroleum_expense_debtor_warning)
