from odoo import fields, models


class PetroleumDepot(models.Model):
    _name = 'petroleum.depot'
    _description = 'Depot / Loading Point'
    _order = 'name'

    name = fields.Char(string='Depot / Loading Point', required=True)
    code = fields.Char(string='Code')
    town = fields.Char(string='Town / Location')
    partner_id = fields.Many2one(
        'res.partner', string='Operator',
        help='Company that operates the depot/terminal (e.g. KPC, an OMC).')
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')
