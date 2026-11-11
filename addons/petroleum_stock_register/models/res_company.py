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
    petro_register_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Stock Register Warehouse', copy=False,
    )
    petro_stock_register_open_date = fields.Date(
        string='Stock Register Opened', copy=False, readonly=True,
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

    def _petro_ensure_register_warehouse(self):
        """Create the warehouse sales and purchases do not use.

        Its sequence sits above the company default so sale orders keep
        the operational warehouse.
        """
        for company in self:
            warehouse = company.petro_register_warehouse_id
            if not warehouse:
                warehouse = self.env['stock.warehouse'].search([
                    ('company_id', '=', company.id),
                    ('code', '=', 'PSR'),
                ], limit=1)
            if not warehouse:
                warehouse = self.env['stock.warehouse'].with_company(company).create({
                    'name': 'Stock Register',
                    'code': 'PSR',
                    'company_id': company.id,
                    'sequence': 100,
                })
            warehouse.write({'petro_register': True, 'sequence': 100})
            warehouse.view_location_id.petro_register = True
            warehouse.lot_stock_id.petro_register = True
            company.petro_register_warehouse_id = warehouse.id
            company._petro_ensure_no_depot_location()
        self.env['petroleum.depot'].search([])._petro_ensure_location()
        return True

    def _petro_ensure_no_depot_location(self):
        self.ensure_one()
        warehouse = self.petro_register_warehouse_id
        if not warehouse:
            return self.env['stock.location']
        location = self.env['stock.location'].search([
            ('company_id', '=', self.id),
            ('petro_no_depot', '=', True),
        ], limit=1)
        if location:
            return location
        return self.env['stock.location'].create({
            'name': 'No depot',
            'usage': 'internal',
            'location_id': warehouse.lot_stock_id.id,
            'company_id': self.id,
            'petro_no_depot': True,
            'petro_register': True,
        })

    def _petro_register_location(self, depot):
        """Internal location for a depot, or the No depot location."""
        self.ensure_one()
        if not self.petro_register_warehouse_id:
            self._petro_ensure_register_warehouse()
        if depot:
            depot._petro_ensure_location()
            return depot._petro_location(self)
        return self._petro_ensure_no_depot_location()
