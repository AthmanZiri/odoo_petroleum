from odoo import fields, models


class PetroleumLoanRepaymentAllocation(models.Model):
    """Principal applied to one loan from a posted repayment journal entry.

    Bulk partner receipts post one bank move and one allocation per loan.
    Outstanding is computed from these rows (plus legacy move scanning).
    """

    _name = 'petroleum.loan.repayment.allocation'
    _description = 'Loan Repayment Allocation'
    _order = 'date, id'

    loan_issued_id = fields.Many2one(
        'petroleum.loan.issued', string='Loan Issued', required=True,
        ondelete='restrict', index=True)
    move_id = fields.Many2one(
        'account.move', string='Journal Entry', required=True,
        ondelete='restrict', index=True)
    amount = fields.Monetary(
        string='Principal Allocated', required=True)
    currency_id = fields.Many2one(
        related='loan_issued_id.currency_id')
    partner_id = fields.Many2one(
        related='loan_issued_id.partner_id', store=True)
    date = fields.Date(
        related='move_id.date', store=True)
    company_id = fields.Many2one(
        related='loan_issued_id.company_id', store=True)
