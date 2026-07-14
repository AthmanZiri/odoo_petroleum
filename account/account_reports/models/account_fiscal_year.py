
"""Community stub for Enterprise account.fiscal.year (account_accountant).

Reports fall back to company fiscalyear_last_day/month when no records exist.
Optional custom fiscal year rows can still be created for non-calendar years.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountFiscalYear(models.Model):
    _name = 'account.fiscal.year'
    _description = 'Fiscal Year'
    _order = 'date_from desc'

    name = fields.Char(string='Name', required=True)
    date_from = fields.Date(
        string='Start Date', required=True,
        help='Start Date, included in the fiscal year.')
    date_to = fields.Date(
        string='End Date', required=True,
        help='Ending Date, included in the fiscal year.')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)

    @api.constrains('date_from', 'date_to', 'company_id')
    def _check_dates(self):
        for fy in self:
            if fy.date_to < fy.date_from:
                raise ValidationError(_(
                    'The ending date must not be prior to the starting date.'))
            overlapping = self.search([
                ('id', '!=', fy.id),
                ('company_id', '=', fy.company_id.id),
                ('date_from', '<=', fy.date_to),
                ('date_to', '>=', fy.date_from),
            ], limit=1)
            if overlapping:
                raise ValidationError(_(
                    'This fiscal year overlaps with an existing fiscal year: %s',
                    overlapping.display_name,
                ))
