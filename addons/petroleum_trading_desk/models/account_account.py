from odoo import api, models


_CASH_NAME_HINTS = ('cash', 'till', 'petty', 'float')


class AccountAccount(models.Model):
    _inherit = 'account.account'

    @api.model_create_multi
    def create(self, vals_list):
        accounts = super().create(vals_list)
        if not self.env.context.get('petroleum_skip_bank_journal'):
            accounts._petroleum_ensure_bank_journals()
        return accounts

    def write(self, vals):
        res = super().write(vals)
        if (
            not self.env.context.get('petroleum_skip_bank_journal')
            and any(key in vals for key in ('account_type', 'company_ids', 'name', 'active'))
        ):
            self._petroleum_ensure_bank_journals()
        return res

    def _petroleum_journal_type_for_account(self):
        self.ensure_one()
        name = (self.name or '').lower()
        if any(hint in name for hint in _CASH_NAME_HINTS):
            return 'cash'
        return 'bank'

    def _petroleum_ensure_bank_journals(self):
        """Open a Bank/Cash journal (cash book) for every Bank and Cash GL."""
        Journal = self.env['account.journal']
        created = Journal.browse()
        for account in self.filtered(lambda a: a.account_type == 'asset_cash' and a.active):
            for company in account.company_ids:
                created |= account._petroleum_ensure_bank_journal(company)
        return created

    def _petroleum_ensure_bank_journal(self, company):
        """Return the Bank/Cash journal whose default account is this GL."""
        self.ensure_one()
        Journal = self.env['account.journal'].with_context(
            petroleum_skip_bank_journal=True)
        existing = Journal.with_context(active_test=False).search([
            ('company_id', '=', company.id),
            ('default_account_id', '=', self.id),
            ('type', 'in', ('bank', 'cash')),
        ], limit=1)
        if existing:
            if not existing.active:
                existing.active = True
            return existing

        journal_type = self._petroleum_journal_type_for_account()
        name = self.name
        name_clash = Journal.with_context(active_test=False).search([
            ('company_id', '=', company.id),
            ('name', '=', name),
        ], limit=1)
        if name_clash:
            if name_clash.default_account_id == self and name_clash.type in ('bank', 'cash'):
                return name_clash
            suffix = self.code or str(self.id)
            name = '%s (%s)' % (self.name, suffix)

        code = Journal._get_next_journal_default_code(journal_type, company)
        if not code:
            code = (self.code or 'BNK')[:5]
        return Journal.create({
            'name': name,
            'code': code,
            'type': journal_type,
            'company_id': company.id,
            'default_account_id': self.id,
        })
