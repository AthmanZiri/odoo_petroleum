from odoo import models, fields


class InvoiceAnalysis(models.Model):
    _name = 'invoice.analysis'
    _description = 'Invoice and Bill Analysis'
    _auto = False
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    move_type = fields.Selection([
        ('out_invoice', 'Customer Invoice'),
        ('in_invoice', 'Vendor Bill'),
        ('out_refund', 'Customer Credit Note'),
        ('in_refund', 'Vendor Credit Note'),
    ], string='Type', readonly=True)
    quantity = fields.Float('Quantity', readonly=True)
    price_unit = fields.Float('Unit Price', readonly=True)
    price_subtotal = fields.Monetary('Subtotal', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    date = fields.Date('Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)

    def init(self):
        self.env.cr.execute(f"DROP VIEW IF EXISTS {self._table}")
        query = f"""
            CREATE VIEW {self._table} AS (
                SELECT
                    aml.id,
                    am.partner_id,
                    aml.product_id,
                    am.move_type,
                    aml.quantity,
                    aml.price_unit,
                    aml.price_subtotal,
                    am.currency_id,
                    am.date,
                    am.company_id
                FROM account_move am
                JOIN account_move_line aml ON am.id = aml.move_id
                WHERE am.move_type IN ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')
                    AND am.state = 'posted'
                    AND aml.product_id IS NOT NULL
            )
        """
        self.env.cr.execute(query)