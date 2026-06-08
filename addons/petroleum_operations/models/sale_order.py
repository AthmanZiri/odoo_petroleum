from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    depot_id = fields.Many2one('petroleum.depot', string='Loading Depot')
    petro_margin_total = fields.Monetary(
        string='Total Margin', compute='_compute_petro_margin', store=True,
        currency_field='currency_id')

    @api.depends('order_line.petro_margin')
    def _compute_petro_margin(self):
        for order in self:
            order.petro_margin_total = sum(order.order_line.mapped('petro_margin'))

    def _create_purchase_orders(self):
        """Back-to-back POs from the supplier and buy price chosen on each line.

        Falls back to the product's first vendor / price when a line has no
        explicit supplier, preserving the original behaviour.
        """
        for order in self:
            existing_pos = self.env['purchase.order'].search([('origin', '=', order.name)])
            if existing_pos:
                continue

            grouped = {}  # supplier -> list of (line, price)
            for line in order.order_line:
                if not (line.product_id and line.product_id.fuel_ok):
                    continue
                supplier = line.petro_supplier_id
                price = line.petro_buy_price
                if not supplier and line.product_id.seller_ids:
                    seller = line.product_id.seller_ids[0]
                    supplier = seller.partner_id
                    if not price:
                        price = seller.price
                if not supplier:
                    continue
                grouped.setdefault(supplier, []).append((line, price))

            for supplier, lines in grouped.items():
                po = self.env['purchase.order'].create({
                    'partner_id': supplier.id,
                    'origin': order.name,
                    'date_order': fields.Datetime.now(),
                    'depot_id': order.depot_id.id if order.depot_id else False,
                })
                for line, price in lines:
                    self.env['purchase.order.line'].create({
                        'order_id': po.id,
                        'name': line.name,
                        'product_id': line.product_id.id,
                        'product_qty': line.product_uom_qty,
                        'product_uom_id': line.product_id.uom_id.id,
                        'price_unit': price,
                        'date_planned': fields.Datetime.now(),
                    })
        return True


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    petro_supplier_id = fields.Many2one(
        'res.partner', string='Supplier',
        domain="[('supplier_rank', '>', 0)]",
        help='Supplier this fuel line will be sourced from (back-to-back).')
    petro_buy_price = fields.Float(
        string='Buy Price', digits='Product Price',
        help='Negotiated supplier cost per unit for this loading.')
    petro_margin = fields.Monetary(
        string='Margin', compute='_compute_petro_margin', store=True,
        currency_field='currency_id')

    @api.onchange('petro_supplier_id', 'product_id')
    def _onchange_petro_supplier(self):
        """Default the buy price from the vendor pricelist when available."""
        for line in self:
            if line.petro_buy_price or not line.product_id:
                continue
            sellers = line.product_id.seller_ids
            if line.petro_supplier_id:
                sellers = sellers.filtered(
                    lambda s: s.partner_id == line.petro_supplier_id)
            if sellers:
                line.petro_buy_price = sellers[0].price

    @api.depends('price_unit', 'petro_buy_price', 'product_uom_qty')
    def _compute_petro_margin(self):
        for line in self:
            line.petro_margin = (line.price_unit - line.petro_buy_price) * line.product_uom_qty

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        if self.petro_buy_price:
            res['petro_buy_price'] = self.petro_buy_price
        return res
