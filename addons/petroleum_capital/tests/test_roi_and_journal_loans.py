from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestRoiAndJournalLoans(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bank_journal = cls.company_data['default_journal_bank']
        cls.investor = cls.env['res.partner'].create({'name': 'ROI Investor'})
        cls.borrower = cls.env['res.partner'].create({'name': 'JE Borrower'})
        cls.capital = cls.env['petroleum.investor.capital'].create({
            'partner_id': cls.investor.id,
            'date': '2026-01-01',
            'amount': 7000000.0,
            'monthly_roi_amount': 250000.0,
            'bank_journal_id': cls.bank_journal.id,
        })
        cls.capital.action_post_opening()

    def _general_journal(self):
        return self.env['petroleum.loan.issued']._ensure_capital_journal(
            self.env.company)

    def _loans_account(self):
        return self.env['petroleum.loan.issued']._ensure_loans_issued_account(
            self.env.company)

    def test_roi_defaults_and_does_not_touch_equity(self):
        wiz = self.env['petroleum.roi.payment'].create({
            'investor_capital_id': self.capital.id,
            'company_id': self.env.company.id,
            'amount': 250000.0,
            'expense_account_id': self.capital.roi_expense_account_id.id,
            'bank_journal_id': self.bank_journal.id,
            'payment_date': fields.Date.today(),
        })
        action = wiz.action_confirm()
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(move.state, 'posted')
        expense = sum(
            move.line_ids.filtered(
                lambda l: l.account_id == self.capital.roi_expense_account_id
            ).mapped('debit')
        )
        bank = sum(
            move.line_ids.filtered(
                lambda l: l.account_id == self.bank_journal.default_account_id
            ).mapped('credit')
        )
        equity = move.line_ids.filtered(
            lambda l: l.account_id == self.capital.equity_account_id)
        self.assertEqual(expense, 250000.0)
        self.assertEqual(bank, 250000.0)
        self.assertFalse(equity)

    def test_roi_zero_amount_refused(self):
        wiz = self.env['petroleum.roi.payment'].create({
            'investor_capital_id': self.capital.id,
            'company_id': self.env.company.id,
            'amount': 0.0,
            'expense_account_id': self.capital.roi_expense_account_id.id,
            'bank_journal_id': self.bank_journal.id,
            'payment_date': fields.Date.today(),
        })
        with self.assertRaises(UserError):
            wiz.action_confirm()

    def test_roi_partner_comes_from_capital(self):
        wiz = self.env['petroleum.roi.payment'].create({
            'investor_capital_id': self.capital.id,
            'company_id': self.env.company.id,
            'amount': 1000.0,
            'expense_account_id': self.capital.roi_expense_account_id.id,
            'bank_journal_id': self.bank_journal.id,
            'payment_date': fields.Date.today(),
        })
        self.assertEqual(wiz.partner_id, self.investor)
        action = wiz.action_confirm()
        move = self.env['account.move'].browse(action['res_id'])
        self.assertTrue(all(
            line.partner_id == self.investor for line in move.line_ids))

    def test_loan_issue_from_general_journal(self):
        loans_account = self._loans_account()
        journal = self._general_journal()
        amount = 5000.0
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'ref': 'Loan issue JE',
            'line_ids': [
                Command.create({
                    'name': 'Loan issued',
                    'account_id': loans_account.id,
                    'partner_id': self.borrower.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': 'Loan issued',
                    'account_id': self.bank_journal.default_account_id.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        self.assertTrue(move.petroleum_loan_issue_unregistered)
        wiz = self.env['petroleum.loan.journal.issue'].create({
            'move_id': move.id,
            'partner_id': self.borrower.id,
            'company_id': self.env.company.id,
            'amount': amount,
            'asset_account_id': loans_account.id,
        })
        action = wiz.action_confirm()
        loan = self.env['petroleum.loan.issued'].browse(action['res_id'])
        self.assertEqual(loan.state, 'posted')
        self.assertEqual(loan.opening_move_id, move)
        self.assertEqual(loan.amount_outstanding, amount)
        self.assertFalse(move.petroleum_loan_issue_unregistered)

    def test_single_line_loan_issue_refused(self):
        loans_account = self._loans_account()
        journal = self._general_journal()
        vals = {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'line_ids': [
                Command.create({
                    'name': 'Unbalanced',
                    'account_id': loans_account.id,
                    'partner_id': self.borrower.id,
                    'debit': 100.0,
                    'credit': 0.0,
                }),
            ],
        }
        with self.assertRaises(UserError):
            self.env['account.move'].create(vals)

    def test_loan_repayment_from_general_journal(self):
        loans_account = self._loans_account()
        loan = self.env['petroleum.loan.issued'].create({
            'partner_id': self.borrower.id,
            'date': '2026-01-01',
            'amount': 1000.0,
            'asset_account_id': loans_account.id,
            'bank_journal_id': self.bank_journal.id,
        })
        loan.action_post_opening()
        journal = self._general_journal()
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'ref': 'Loan repay JE',
            'line_ids': [
                Command.create({
                    'name': 'Repayment',
                    'account_id': self.bank_journal.default_account_id.id,
                    'debit': 400.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': 'Repayment',
                    'account_id': loans_account.id,
                    'partner_id': self.borrower.id,
                    'debit': 0.0,
                    'credit': 400.0,
                }),
            ],
        })
        move.action_post()
        self.assertTrue(move.petroleum_loan_repay_unallocated)
        wiz = self.env['petroleum.loan.journal.repay'].create({
            'move_id': move.id,
            'partner_id': self.borrower.id,
            'company_id': self.env.company.id,
            'amount': 400.0,
        })
        wiz._apply_fifo()
        wiz.action_confirm()
        self.assertEqual(loan.amount_outstanding, 600.0)
        self.assertEqual(loan.amount_repaid, 400.0)
        self.assertFalse(move.petroleum_loan_repay_unallocated)

    def test_drafting_repayment_clears_allocation(self):
        loans_account = self._loans_account()
        loan = self.env['petroleum.loan.issued'].create({
            'partner_id': self.borrower.id,
            'date': '2026-01-01',
            'amount': 1000.0,
            'asset_account_id': loans_account.id,
            'bank_journal_id': self.bank_journal.id,
        })
        loan.action_post_opening()
        journal = self._general_journal()
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'line_ids': [
                Command.create({
                    'name': 'Repayment',
                    'account_id': self.bank_journal.default_account_id.id,
                    'debit': 200.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': 'Repayment',
                    'account_id': loans_account.id,
                    'partner_id': self.borrower.id,
                    'debit': 0.0,
                    'credit': 200.0,
                }),
            ],
        })
        move.action_post()
        wiz = self.env['petroleum.loan.journal.repay'].create({
            'move_id': move.id,
            'partner_id': self.borrower.id,
            'company_id': self.env.company.id,
            'amount': 200.0,
        })
        wiz._apply_fifo()
        wiz.action_confirm()
        self.assertEqual(loan.amount_outstanding, 800.0)
        move.button_draft()
        self.assertEqual(loan.amount_outstanding, 1000.0)
        self.assertFalse(loan.repayment_allocation_ids)
