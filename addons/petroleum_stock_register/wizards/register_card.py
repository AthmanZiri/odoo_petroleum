from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PetroleumStockRegisterCard(models.TransientModel):
    _name = 'petroleum.stock.register.card'
    _description = 'Depot Stock Card'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('fuel_ok', '=', True)]",
    )
    depot_id = fields.Many2one('petroleum.depot', string='Depot')
    no_depot = fields.Boolean(string='No depot')
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    line_ids = fields.One2many(
        'petroleum.stock.register.card.line', 'card_id', string='Lines',
    )

    @api.constrains('depot_id', 'no_depot', 'date_from', 'date_to')
    def _check_card(self):
        for card in self:
            if not card.depot_id and not card.no_depot:
                raise ValidationError(_('Choose a depot, or the No depot bucket.'))
            if card.depot_id and card.no_depot:
                raise ValidationError(_('Choose a depot or the No depot bucket, not both.'))
            if card.date_from and card.date_to and card.date_from > card.date_to:
                raise ValidationError(_('The start date is after the end date.'))

    def action_build(self):
        self.ensure_one()
        self.line_ids.unlink()
        company = self.company_id
        if self.no_depot:
            location = company._petro_ensure_no_depot_location()
        else:
            location = company._petro_register_location(self.depot_id)
        if not location:
            return True
        moves = self.env['stock.move'].search([
            ('petro_register', '=', True),
            ('state', '=', 'done'),
            ('company_id', '=', company.id),
            ('product_id', '=', self.product_id.id),
            ('petro_business_date', '>=', self.date_from),
            ('petro_business_date', '<=', self.date_to),
            '|',
            ('location_id', '=', location.id),
            ('location_dest_id', '=', location.id),
        ], order='petro_business_date, id')
        balance = 0.0
        lines = []
        for move in moves:
            qty_in = move.quantity if move.location_dest_id == location else 0.0
            qty_out = move.quantity if move.location_id == location else 0.0
            balance += qty_in - qty_out
            lines.append({
                'card_id': self.id,
                'business_date': move.petro_business_date,
                'origin': move.origin,
                'qty_in': qty_in,
                'qty_out': qty_out,
                'balance': balance,
            })
        if lines:
            self.env['petroleum.stock.register.card.line'].create(lines)
        return True


class PetroleumStockRegisterCardLine(models.TransientModel):
    _name = 'petroleum.stock.register.card.line'
    _description = 'Depot Stock Card Line'
    _order = 'business_date, id'

    card_id = fields.Many2one(
        'petroleum.stock.register.card', required=True, ondelete='cascade',
    )
    business_date = fields.Date()
    origin = fields.Char()
    qty_in = fields.Float(string='Litres In', digits='Product Unit of Measure')
    qty_out = fields.Float(string='Litres Out', digits='Product Unit of Measure')
    balance = fields.Float(string='Balance', digits='Product Unit of Measure')
