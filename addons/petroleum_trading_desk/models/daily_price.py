from odoo import api, fields, models, _


class PetroleumDailyPrice(models.Model):
    _name = 'petroleum.daily.price'
    _description = 'Daily Fuel Price'
    _order = 'date desc, product_id'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('fuel_ok', '=', True)]")
    depot_id = fields.Many2one('petroleum.depot', string='Depot')
    supplier_id = fields.Many2one(
        'res.partner', string='Supplier', domain="[('supplier_rank', '>', 0)]")
    buy_price = fields.Float(string='Buy Price', digits='Product Price')
    sell_price = fields.Float(string='Sell Price', digits='Product Price')
    margin = fields.Float(string='Margin', compute='_compute_margin', store=True,
                          digits='Product Price')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    note = fields.Char(string='Note')

    @api.depends('buy_price', 'sell_price')
    def _compute_margin(self):
        for rec in self:
            rec.margin = rec.sell_price - rec.buy_price

    @api.model
    def get_latest(self, product_id, supplier_id=False):
        """Return the most recent price line for a product (optionally supplier)."""
        domain = [('product_id', '=', product_id)]
        if supplier_id:
            domain.append(('supplier_id', '=', supplier_id))
        return self.search(domain, order='date desc, id desc', limit=1)

    @api.model
    def action_carry_forward(self):
        """Roll yesterday's prices into today for every fuel product that
        doesn't yet have a price line for today. Lets the trader open the
        board each morning and just tweak the numbers that changed."""
        today = fields.Date.context_today(self)
        products = self.env['product.product'].search([('fuel_ok', '=', True)])
        for product in products:
            if self.search_count([('product_id', '=', product.id),
                                  ('date', '=', today)]):
                continue
            latest = self.search([('product_id', '=', product.id),
                                  ('date', '<', today)],
                                 order='date desc, id desc', limit=1)
            if latest:
                self.create({
                    'product_id': product.id,
                    'depot_id': latest.depot_id.id,
                    'supplier_id': latest.supplier_id.id,
                    'buy_price': latest.buy_price,
                    'sell_price': latest.sell_price,
                })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Daily Prices'),
            'res_model': 'petroleum.daily.price',
            'view_mode': 'list',
            'domain': [('date', '=', today)],
            'target': 'current',
        }
