import logging

from odoo import models
from odoo.addons.sale.models.sale_order import SaleOrder as BaseSaleOrder

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _petro_all_lines_are_fuel(self):
        self.ensure_one()
        lines = self.order_line.filtered(
            lambda line: not line.display_type and line.product_id)
        return bool(lines) and all(line.product_id.fuel_ok for line in lines)

    def action_confirm(self):
        """Confirm fuel orders without the warehouse automation.

        Sale automation would validate a delivery and post an invoice when
        the warehouse flags are on. Fuel never takes that path. Procurement
        for fuel is skipped as well, so no delivery is created.
        """
        fuel_orders = self.filtered(lambda order: order._petro_all_lines_are_fuel())
        other = self - fuel_orders
        if other:
            super(SaleOrder, other).action_confirm()
        if fuel_orders:
            BaseSaleOrder.action_confirm(fuel_orders)
            stray = fuel_orders.picking_ids.filtered(
                lambda picking: picking.state != 'cancel')
            if stray:
                _logger.error(
                    'Fuel sale %s created pickings %s. Cancelling any that '
                    'are not already done.',
                    ', '.join(fuel_orders.mapped('name')),
                    ', '.join(stray.mapped('name')),
                )
                cancelable = stray.filtered(
                    lambda picking: picking.state not in ('done', 'cancel'))
                if cancelable:
                    cancelable.action_cancel()
        return True
