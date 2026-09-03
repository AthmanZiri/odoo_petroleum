from odoo import fields, models


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    trip_id = fields.Many2one('trip.management', string='Trip')

    def _petroleum_staff_claims_journal(self, company):
        company._petroleum_ensure_staff_claims_journal()
        if company.expense_journal_id and company.expense_journal_id.type != 'purchase':
            return company.expense_journal_id
        return self.env['account.journal'].search([
            *self.env['account.journal']._check_company_domain(company),
            ('code', '=', 'STCLM'),
        ], limit=1)

    def _post_without_wizard(self):
        """Post employee claims on Staff Claims, never the Purchase journal."""
        self._check_can_create_move()
        today = fields.Date.context_today(self)
        employee_expenses = self.filtered(
            lambda expense: expense.payment_mode == 'own_account')
        fallback = self.env['hr.expense']

        for company, expenses in employee_expenses.grouped('company_id').items():
            expenses = expenses.with_company(company)
            journal = expenses._petroleum_staff_claims_journal(company)
            if not journal:
                fallback |= expenses
                continue
            expense_receipt_vals_list = [
                {
                    **new_receipt_vals,
                    'journal_id': journal.id,
                    'invoice_date': today,
                }
                for new_receipt_vals in expenses._prepare_receipts_vals()
            ]
            moves = self.env['account.move'].sudo().create(expense_receipt_vals_list)
            for move in moves:
                move._message_set_main_attachment_id(
                    move.attachment_ids, force=True, filter_xml=False)
            moves.action_post()
        if fallback:
            super(HrExpense, fallback)._post_without_wizard()
