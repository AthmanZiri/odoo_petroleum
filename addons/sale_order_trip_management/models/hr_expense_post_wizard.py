from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrExpensePostWizard(models.TransientModel):
    _inherit = 'hr.expense.post.wizard'

    @api.model
    def _default_journal_id(self):
        company = self.env.company
        company._petroleum_ensure_staff_claims_journal()
        if company.expense_journal_id and company.expense_journal_id.type != 'purchase':
            return company.expense_journal_id.id
        return super()._default_journal_id()

    employee_journal_id = fields.Many2one(
        domain="[('type', '=', 'general')]",
        default=_default_journal_id,
        help='Staff Claims (general journal), not Purchase / Bills.',
    )

    def action_post_entry(self):
        if self.employee_journal_id.type == 'purchase':
            raise UserError(_(
                'Staff reimbursements cannot post to the Purchase journal. '
                'That inflates purchases and distorts gross profit. '
                'Use the Staff Claims journal.'
            ))
        return super().action_post_entry()
