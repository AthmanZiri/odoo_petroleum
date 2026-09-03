from odoo import fields, models


STAFF_CLAIMS_JOURNAL_CODE = 'STCLM'
STAFF_CLAIMS_JOURNAL_NAME = 'Staff Claims'


class ResCompany(models.Model):
    _inherit = 'res.company'

    expense_journal_id = fields.Many2one(
        domain="[('type', '=', 'general')]",
        help='Staff reimbursements post here. Use Staff Claims (general), '
             'not the Purchase journal used for supplier bills.',
    )

    def _petroleum_ensure_staff_claims_journal(self):
        """Cash book for employee claims — not the Purchase / Bills journal."""
        Journal = self.env['account.journal']
        for company in self:
            journal = Journal.search([
                ('company_id', '=', company.id),
                ('code', '=', STAFF_CLAIMS_JOURNAL_CODE),
            ], limit=1)
            if not journal:
                journal = Journal.search([
                    ('company_id', '=', company.id),
                    ('name', '=', STAFF_CLAIMS_JOURNAL_NAME),
                    ('type', '=', 'general'),
                ], limit=1)
            if not journal:
                journal = Journal.create({
                    'name': STAFF_CLAIMS_JOURNAL_NAME,
                    'code': STAFF_CLAIMS_JOURNAL_CODE,
                    'type': 'general',
                    'company_id': company.id,
                })
            current = company.expense_journal_id
            if not current or current.type == 'purchase':
                company.expense_journal_id = journal
        return True
