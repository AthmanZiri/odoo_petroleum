from odoo import api, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    @api.model
    def _create_default_account(self, company, journal_type, vals):
        """Avoid a second journal when Odoo creates the journal's own GL."""
        return super(
            AccountJournal,
            self.with_context(petroleum_skip_bank_journal=True),
        )._create_default_account(company, journal_type, vals)
