from odoo import _, models
from odoo.exceptions import UserError
from odoo.fields import Command


class PetroleumCapitalMixin(models.AbstractModel):
    """Shared helpers: COA accounts + dedicated Capital & Loans journal."""

    _name = 'petroleum.capital.mixin'
    _description = 'Petroleum Capital Helpers'

    def _next_account_code(self, company, base):
        Account = self.env['account.account']
        existing = Account.search_count([
            ('company_ids', 'in', company.id),
            ('code', '=', base),
        ])
        return base if not existing else '%s%s' % (base, existing)

    def _ensure_account(self, company, name, code_base, account_type):
        Account = self.env['account.account']
        acc = Account.search([
            ('company_ids', 'in', company.id),
            ('name', '=', name),
        ], limit=1)
        if acc:
            return acc
        return Account.create({
            'name': name,
            'code': self._next_account_code(company, code_base),
            'account_type': account_type,
            'company_ids': [Command.link(company.id)],
        })

    def _ensure_opening_clearing_account(self, company):
        """Equity clearing used as the contra for cut-over openings."""
        return self._ensure_account(
            company,
            'Opening Balance Import',
            'OPNBAL',
            'equity',
        )

    def _ensure_investor_equity_account(self, company):
        return self._ensure_account(
            company,
            'Investor Capital',
            'EQUINV',
            'equity',
        )

    def _ensure_roi_expense_account(self, company):
        return self._ensure_account(
            company,
            'Return on Investment',
            'EXPROI',
            'expense',
        )

    def _ensure_loans_issued_account(self, company):
        return self._ensure_account(
            company,
            'Loans Issued',
            'ASTLN',
            'asset_current',
        )

    def _ensure_loan_interest_account(self, company):
        return self._ensure_account(
            company,
            'Loan Interest Income',
            'INCLN',
            'income',
        )

    def _ensure_capital_journal(self, company):
        """Dedicated general journal — not the default Miscellaneous Operations."""
        Journal = self.env['account.journal']
        journal = Journal.search([
            ('company_id', '=', company.id),
            ('code', '=', 'CAPLN'),
        ], limit=1)
        if journal:
            return journal
        journal = Journal.search([
            ('company_id', '=', company.id),
            ('name', '=', 'Capital & Loans'),
            ('type', '=', 'general'),
        ], limit=1)
        if journal:
            return journal
        return Journal.create({
            'name': 'Capital & Loans',
            'code': 'CAPLN',
            'type': 'general',
            'company_id': company.id,
        })

    def _contra_account_for_opening(self, company, bank_journal=None):
        """Bank default account when cash is known; else opening equity clearing."""
        if bank_journal:
            if not bank_journal.default_account_id:
                raise UserError(_(
                    'Bank journal "%s" has no default account configured.'
                ) % bank_journal.display_name)
            return bank_journal.default_account_id
        return self._ensure_opening_clearing_account(company)

    def _post_balanced_entry(
        self, company, journal, date, ref, debit_account, credit_account,
        amount, partner=None, line_name=None,
    ):
        if amount <= 0:
            raise UserError(_('Amount must be positive.'))
        name = line_name or ref
        partner_id = partner.id if partner else False
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': date,
            'ref': ref,
            'company_id': company.id,
            'line_ids': [
                Command.create({
                    'name': name,
                    'account_id': debit_account.id,
                    'partner_id': partner_id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': name,
                    'account_id': credit_account.id,
                    'partner_id': partner_id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move
