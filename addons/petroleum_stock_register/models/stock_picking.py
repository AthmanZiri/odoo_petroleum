from odoo import _, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        if not self.env.context.get('petro_register_move'):
            protected = self.browse()
            for picking in self:
                locations = picking.location_id | picking.location_dest_id
                locations |= picking.move_ids.location_id | picking.move_ids.location_dest_id
                if any(location._petro_is_register() for location in locations):
                    protected |= picking
            if protected:
                raise UserError(_(
                    'Transfers through the stock register are posted from '
                    'Daily Position. %(pickings)s cannot be validated by hand.',
                    pickings=', '.join(protected.mapped('name')),
                ))
        return super().button_validate()
