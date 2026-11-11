from odoo import api, fields, models
from odoo.tools.float_utils import float_compare


class PetroleumDepot(models.Model):
    _inherit = 'petroleum.depot'

    @api.model_create_multi
    def create(self, vals_list):
        depots = super().create(vals_list)
        depots._petro_ensure_location()
        return depots

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals:
            self._petro_ensure_location()
        return res

    def unlink(self):
        """Archive the depot location. A same-name keeper receives the litres."""
        Location = self.env['stock.location'].sudo()
        for depot in self:
            locations = Location.search([('petro_depot_id', '=', depot.id)])
            keeper = self.search([
                ('id', 'not in', self.ids),
                ('name', '=ilike', (depot.name or '').strip()),
            ], limit=1)
            for location in locations:
                if keeper:
                    keeper._petro_ensure_location()
                    keeper_location = keeper._petro_location(location.company_id)
                    if keeper_location and keeper_location != location:
                        self._petro_transfer_on_hand(location, keeper_location)
                location.write({'active': False, 'petro_depot_id': False})
        return super().unlink()

    def _petro_location(self, company):
        self.ensure_one()
        return self.env['stock.location'].search([
            ('petro_depot_id', '=', self.id),
            ('company_id', '=', company.id),
        ], limit=1)

    def _petro_ensure_location(self):
        companies = self.env['res.company'].search([
            ('petro_register_warehouse_id', '!=', False),
        ])
        for depot in self:
            for company in companies:
                warehouse = company.petro_register_warehouse_id
                location = depot._petro_location(company)
                if location:
                    location.write({
                        'name': depot.name,
                        'active': True,
                        'petro_register': True,
                        'location_id': warehouse.lot_stock_id.id,
                    })
                    continue
                self.env['stock.location'].create({
                    'name': depot.name,
                    'usage': 'internal',
                    'location_id': warehouse.lot_stock_id.id,
                    'company_id': company.id,
                    'petro_depot_id': depot.id,
                    'petro_register': True,
                })

    def _petro_transfer_on_hand(self, source, destination):
        quants = self.env['stock.quant'].sudo().search([
            ('location_id', '=', source.id),
            ('quantity', '>', 0),
        ])
        today = fields.Date.context_today(self)
        Move = self.env['stock.move']
        for quant in quants:
            rounding = quant.product_id.uom_id.rounding or 0.01
            if float_compare(quant.quantity, 0.0, precision_rounding=rounding) <= 0:
                continue
            Move._petro_post_register_move(
                quant.product_id, source, destination, quant.quantity,
                source.company_id or self.env.company,
                'Depot merge', today,
            )


