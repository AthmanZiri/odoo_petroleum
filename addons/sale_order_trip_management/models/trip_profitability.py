from odoo import models, fields, api, tools


class TripProfitability(models.Model):
    _name = 'trip.profitability'
    _description = 'Trip Profitability Report'
    _auto = False
    _rec_name = 'trip_id'

    trip_id = fields.Many2one('trip.management', string='Trip')
    trip_name = fields.Char(string='Trip Reference')
    sale_order_id = fields.Many2one('sale.order', string='Sale Order')
    customer_name = fields.Char(string='Customer')
    product_id = fields.Many2one('product.product', string='Product')
    default_code = fields.Char(string='Product')
    invoice_amount = fields.Monetary(string='Invoice Amount')
    billed_amount = fields.Monetary(string='Billed Amount')
    expense_amount = fields.Monetary(string='Expense Amount')
    profit = fields.Monetary(string='Profit')
    currency_id = fields.Many2one('res.currency', string='Currency')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER() AS id,
                    t.id AS trip_id,
                    t.name AS trip_name,
                    ts.sale_order_id AS sale_order_id,
                    rp.name AS customer_name,
                    sol.product_id AS product_id,
                    pt.default_code AS default_code,
                    COALESCE(inv.invoice_total, 0) AS invoice_amount,
                    COALESCE(bill.bill_total, 0) AS billed_amount,
                    COALESCE(exp.total_expenses, 0) AS expense_amount,
                    (COALESCE(inv.invoice_total, 0) - COALESCE(bill.bill_total, 0) - COALESCE(exp.total_expenses, 0)) AS profit,
                    so.currency_id AS currency_id
                FROM trip_management t
                LEFT JOIN trip_sale ts ON ts.trip_id = t.id
                LEFT JOIN sale_order so ON so.id = ts.sale_order_id
                LEFT JOIN res_partner rp ON rp.id = so.partner_id
                LEFT JOIN sale_order_line sol ON sol.order_id = so.id
                LEFT JOIN product_product pp ON pp.id = sol.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN (
                    SELECT 
                        sol.order_id as sale_order_id,
                        SUM(am.amount_total) as invoice_total
                    FROM sale_order_line sol
                    LEFT JOIN sale_order_line_invoice_rel solir ON solir.order_line_id = sol.id
                    LEFT JOIN account_move_line aml ON aml.id = solir.invoice_line_id
                    LEFT JOIN account_move am ON am.id = aml.move_id AND am.move_type = 'out_invoice' AND am.state = 'posted'
                    WHERE am.id IS NOT NULL
                    GROUP BY sol.order_id
                ) inv ON inv.sale_order_id = so.id
                LEFT JOIN (
                    SELECT 
                        po.id as purchase_order_id,
                        SUM(am.amount_total) as bill_total
                    FROM purchase_order po
                    LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
                    LEFT JOIN account_move_line aml ON aml.purchase_line_id = pol.id
                    LEFT JOIN account_move am ON am.id = aml.move_id AND am.move_type = 'in_invoice' AND am.state = 'posted'
                    WHERE am.id IS NOT NULL
                    GROUP BY po.id
                ) bill ON bill.purchase_order_id = t.purchase_order_id
                LEFT JOIN (
                    SELECT 
                        tse.trip_id,
                        SUM(COALESCE(he.total_amount, 0)) AS total_expenses
                    FROM trip_sale_expense tse
                    LEFT JOIN hr_expense he ON he.id = tse.expense_id
                    GROUP BY tse.trip_id
                    UNION ALL
                    SELECT 
                        he.trip_id,
                        SUM(COALESCE(he.total_amount, 0)) AS total_expenses
                    FROM hr_expense he
                    WHERE he.trip_id IS NOT NULL
                    GROUP BY he.trip_id
                ) exp ON exp.trip_id = t.id
                WHERE ts.sale_order_id IS NOT NULL AND sol.product_id IS NOT NULL
            )
        """ % self._table)