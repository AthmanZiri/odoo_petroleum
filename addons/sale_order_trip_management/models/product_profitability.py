from odoo import models, fields, api, tools


class ProductProfitability(models.Model):
    _name = 'product.profitability'
    _description = 'Product Profitability Report'
    _auto = False
    _rec_name = 'product_id'

    order_date = fields.Date(string='Order Date')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order')
    customer_name = fields.Char(string='Customer')
    invoice_date = fields.Date(string='Invoice Date')
    trip_id = fields.Many2one('trip.management', string='Trip')
    trip_name = fields.Char(string='Trip Reference')
    product_id = fields.Many2one('product.product', string='Product')
    default_code = fields.Char(string='Product')
    truck_id = fields.Many2one('truck.management', string='Truck')
    sale_price = fields.Float(string='Sale Price')
    purchase_price = fields.Float(string='Purchase Price')
    qty_sold = fields.Float(string='Qty Sold')
    qty_bought = fields.Float(string='Qty Bought')
    sale_amount = fields.Float(string='Sale Amount')
    purchase_amount = fields.Float(string='Purchase Amount')
    gross_profit = fields.Float(string='Gross Profit')
    expense_amount = fields.Float(string='Expense Amount')
    net_profit = fields.Float(string='Net Profit')
    currency_id = fields.Many2one('res.currency', string='Currency')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER() AS id,
                    so.date_order AS order_date,
                    ts.sale_order_id AS sale_order_id,
                    rp.name AS customer_name,
                    am.invoice_date AS invoice_date,
                    t.id AS trip_id,
                    t.name AS trip_name,
                    sol.product_id AS product_id,
                    pt.default_code AS default_code,
                    t.truck_id AS truck_id,
                    sol.price_unit AS sale_price,
                    COALESCE(pol.price_unit, 0) AS purchase_price,
                    sol.product_uom_qty AS qty_sold,
                    COALESCE(pol.product_qty, 0) AS qty_bought,
                    sol.price_unit * sol.product_uom_qty AS sale_amount,
                    COALESCE(pol.price_unit, 0) * COALESCE(pol.product_qty, 0) AS purchase_amount,
                    (sol.price_unit - COALESCE(pol.price_unit, 0)) * sol.product_uom_qty AS gross_profit,
                    COALESCE(exp.expense_amount, 0) AS expense_amount,
                    ((sol.price_unit - COALESCE(pol.price_unit, 0)) * sol.product_uom_qty) - COALESCE(exp.expense_amount, 0) AS net_profit,
                    so.currency_id AS currency_id
                FROM trip_management t
                LEFT JOIN trip_sale ts ON ts.trip_id = t.id
                LEFT JOIN sale_order so ON so.id = ts.sale_order_id
                LEFT JOIN res_partner rp ON rp.id = so.partner_id
                LEFT JOIN sale_order_line sol ON sol.order_id = so.id
                LEFT JOIN product_product pp ON pp.id = sol.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN purchase_order po ON po.id = t.purchase_order_id
                LEFT JOIN purchase_order_line pol ON pol.order_id = po.id AND pol.product_id = sol.product_id
                LEFT JOIN (
                    SELECT 
                        tse.sale_order_id,
                        SUM(COALESCE(he.total_amount, 0)) AS expense_amount
                    FROM trip_sale_expense tse
                    LEFT JOIN hr_expense he ON he.id = tse.expense_id
                    GROUP BY tse.sale_order_id
                ) exp ON exp.sale_order_id = so.id
                LEFT JOIN sale_order_line_invoice_rel solir ON solir.order_line_id = sol.id
                LEFT JOIN account_move_line aml ON aml.id = solir.invoice_line_id
                LEFT JOIN account_move am ON am.id = aml.move_id AND am.move_type = 'out_invoice'
                WHERE sol.product_id IS NOT NULL
            )
        """ % self._table)