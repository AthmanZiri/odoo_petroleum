from odoo import _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero


def post_init_hook(env):
    """Fresh installs arm the register and create its warehouse. Quantities stay at zero."""
    companies = env['res.company'].search([])
    companies._petro_try_arm_stock_register()
    companies._petro_ensure_register_warehouse()


def uninstall_hook(env):
    """Refuse to drop the module while depot locations still hold litres."""
    quants = env['stock.quant'].sudo().search([
        ('location_id.petro_register', '=', True),
    ])
    held = quants.filtered(
        lambda quant: not float_is_zero(
            quant.quantity,
            precision_rounding=quant.product_uom_id.rounding or 0.01,
        ))
    if held:
        raise UserError(_(
            'Reverse the stock register before uninstalling it. '
            'Depot locations still hold litres.'
        ))
