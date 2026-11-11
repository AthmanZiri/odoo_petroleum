from odoo import _, models
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _apply_inventory(self, date=None):
        if not self.env.context.get('petro_register_move'):
            protected = self.filtered(
                lambda quant: quant.location_id._petro_is_register())
            if protected:
                raise UserError(_(
                    'Depot quantities are copied from Daily Position. '
                    'Revise the litres on the board. An inventory adjustment '
                    'on %(location)s is refused.',
                    location=', '.join(protected.location_id.mapped('display_name')),
                ))
        return super()._apply_inventory(date=date)
