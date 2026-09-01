from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestLoanPartnerRepayment(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'FIFO Borrower'})
        cls.bank_journal = cls.company_data['default_journal_bank']
        Loan = cls.env['petroleum.loan.issued']
        cls.loan1 = Loan.create({
            'partner_id': cls.partner.id,
            'date': '2026-01-01',
            'amount': 100.0,
            'bank_journal_id': cls.bank_journal.id,
        })
        cls.loan2 = Loan.create({
            'partner_id': cls.partner.id,
            'date': '2026-02-01',
            'amount': 100.0,
            'bank_journal_id': cls.bank_journal.id,
        })
        cls.loan3 = Loan.create({
            'partner_id': cls.partner.id,
            'date': '2026-03-01',
            'amount': 100.0,
            'bank_journal_id': cls.bank_journal.id,
        })
        (cls.loan1 | cls.loan2 | cls.loan3).action_post_opening()

    def _wizard(self, amount, interest=0.0):
        wiz = self.env['petroleum.loan.partner.repayment'].create({
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
            'amount': amount,
            'interest_amount': interest,
            'bank_journal_id': self.bank_journal.id,
            'payment_date': fields.Date.today(),
        })
        wiz._apply_fifo()
        if interest:
            wiz.interest_account_id = wiz._ensure_loan_interest_account(
                self.env.company)
        return wiz

    def test_fifo_allocates_oldest_first(self):
        wiz = self._wizard(250.0)
        wiz.action_confirm()
        self.assertEqual(self.loan1.amount_outstanding, 0.0)
        self.assertEqual(self.loan2.amount_outstanding, 0.0)
        self.assertEqual(self.loan3.amount_outstanding, 50.0)
        self.assertEqual(self.loan1.amount_repaid, 100.0)
        self.assertEqual(self.loan2.amount_repaid, 100.0)
        self.assertEqual(self.loan3.amount_repaid, 50.0)

    def test_overpay_refused(self):
        wiz = self._wizard(301.0)
        with self.assertRaises(UserError):
            wiz.action_confirm()
        self.assertEqual(self.loan1.amount_outstanding, 100.0)
        self.assertEqual(self.loan2.amount_outstanding, 100.0)
        self.assertEqual(self.loan3.amount_outstanding, 100.0)

    def test_interest_does_not_reduce_principal(self):
        wiz = self._wizard(250.0, interest=10.0)
        action = wiz.action_confirm()
        self.assertEqual(self.loan3.amount_outstanding, 50.0)
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(sum(move.line_ids.mapped('debit')), 260.0)
        interest_lines = move.line_ids.filtered(
            lambda l: l.credit and l.account_id.account_type in (
                'income', 'income_other'))
        self.assertEqual(sum(interest_lines.mapped('credit')), 10.0)

    def test_single_loan_repayment_still_updates_only_that_loan(self):
        wiz = self.env['petroleum.loan.repayment'].create({
            'loan_issued_id': self.loan2.id,
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
            'amount': 40.0,
            'bank_journal_id': self.bank_journal.id,
            'payment_date': fields.Date.today(),
        })
        wiz.action_confirm()
        self.assertEqual(self.loan1.amount_outstanding, 100.0)
        self.assertEqual(self.loan2.amount_outstanding, 60.0)
        self.assertEqual(self.loan3.amount_outstanding, 100.0)
        self.assertTrue(self.loan2.repayment_allocation_ids)
