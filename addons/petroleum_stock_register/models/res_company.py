import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    petro_stock_register_mode = fields.Selection(
        [
            ('firewall', 'Firewall'),
            ('armed', 'Armed'),
            ('live', 'Live'),
        ],
        string='Stock Register',
        default='firewall',
        required=True,
        help='Firewall blocks fuel pickings. Armed tracks litres with on-hand '
             'still at zero. Live copies Daily Position into depot locations.',
    )

    def _petro_stock_register_valuation_blocked(self):
        """Perpetual valuation would post fuel into the books on top of the vendor bill."""
        self.ensure_one()
        if self.inventory_valuation == 'real_time':
            return True
        products = self.env['product.product'].with_company(self).search([
            ('fuel_ok', '=', True),
        ])
        return any(product.valuation == 'real_time' for product in products)

    def action_arm_stock_register(self):
        """Mark fuel as tracked and leave invoicing on ordered litres.

        Refused while valuation is perpetual. Does not post quantities.
        """
        for company in self:
            if company.petro_stock_register_mode == 'live':
                continue
            if company._petro_stock_register_valuation_blocked():
                raise UserError(_(
                    'Stock register stays in firewall mode for %(company)s. '
                    'Fuel valuation is Perpetual (at invoicing), which would '
                    'post stock journals on top of the vendor bill.',
                    company=company.display_name,
                ))
            templates = self.env['product.template'].with_company(company).search([
                ('fuel_ok', '=', True),
                ('is_storable', '=', False),
            ])
            if templates:
                templates.write({'is_storable': True})
            company.petro_stock_register_mode = 'armed'
        return True

    def _petro_try_arm_stock_register(self):
        """Arm every company that can track litres without touching the books."""
        for company in self:
            if company.petro_stock_register_mode == 'live':
                continue
            if company._petro_stock_register_valuation_blocked():
                _logger.warning(
                    'Petroleum stock register left in firewall mode for %s '
                    'because fuel valuation is perpetual.',
                    company.display_name,
                )
                continue
            company.action_arm_stock_register()
