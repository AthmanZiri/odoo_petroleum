# -*- coding: utf-8 -*-


from odoo import fields, models


class AccountLockDate(models.TransientModel):
    """
    Community adaptation: Enterprise defines account.change.lock.date in
    account_accountant. Hook report external-value generation into the
    Cybrosys kit lock wizard instead.
    """
    _inherit = 'account.lock.date'

    def _get_current_period_dates(self, lock_date_field):
        """Approximate the fiscal period used when a lock date is set."""
        self.ensure_one()
        company = self.company_id
        lock_date = getattr(self, lock_date_field, None) or fields.Date.context_today(self)
        date_to = fields.Date.to_date(lock_date)
        # Prefer company fiscal year start when available, else first of month.
        year_start = getattr(company, 'compute_fiscalyear_dates', None)
        if callable(year_start):
            dates = company.compute_fiscalyear_dates(date_to)
            date_from = dates.get('date_from') or date_to.replace(day=1)
        else:
            date_from = date_to.replace(day=1)
        return date_from, date_to

    def _create_default_report_external_values(self, lock_date_field):
        """Create carry-over external values for locked periods when locking."""
        date_from, date_to = self._get_current_period_dates(lock_date_field)
        self.env['account.report']._generate_default_external_values(
            date_from, date_to, lock_date_field == 'tax_lock_date',
        )

    def execute(self):
        res = super().execute()
        # Kit wizard fields differ from Enterprise; generate for hard lock when set.
        for wizard in self:
            if wizard.hard_lock_date:
                wizard._create_default_report_external_values('hard_lock_date')
        return res
