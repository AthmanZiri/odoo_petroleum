from odoo import api, fields, models
from odoo.tools.float_utils import float_compare


class StockMove(models.Model):
    _inherit = 'stock.move'

    petro_register = fields.Boolean(
        string='Petroleum Stock Register', copy=False, index=True,
    )
    petro_business_date = fields.Date(string='Business Date', copy=False)
    petro_reversal_of_id = fields.Many2one(
        'stock.move', string='Reverses', copy=False, index=True,
    )
    petro_reversal_move_id = fields.Many2one(
        'stock.move', string='Reversed By', copy=False,
    )

    @api.model
    def _petro_post_register_move(self, product, source, destination, quantity, company, origin, business_date):
        """Post a done, quantity-only move that is not a sale or purchase picking."""
        rounding = product.uom_id.rounding or 0.01
        if float_compare(quantity, 0.0, precision_rounding=rounding) <= 0:
            return self.browse()
        if product.with_company(company).valuation == 'real_time':
            return self.browse()
        move = self.with_context(petro_register_move=True).create({
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': quantity,
            'location_id': source.id,
            'location_dest_id': destination.id,
            'company_id': company.id,
            'state': 'confirmed',
            'is_inventory': True,
            'origin': origin,
            'petro_register': True,
            'petro_business_date': business_date,
            'move_line_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'quantity': quantity,
                'location_id': source.id,
                'location_dest_id': destination.id,
                'company_id': company.id,
            })],
        })
        move.move_line_ids.picked = True
        move._action_done()
        move.write({
            'date': fields.Datetime.to_datetime(business_date),
            'petro_business_date': business_date,
        })
        return move
