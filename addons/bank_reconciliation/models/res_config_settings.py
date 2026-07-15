# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bank_rec_payment_tolerance = fields.Float(
        string='Bank Payment Tolerance',
        config_parameter='bank_reconciliation.payment_tolerance',
        help='Relative tolerance (e.g. 0.03 = 3%) when matching bank statement '
             'lines to invoices/payments. Small leftover differences within this '
             'ratio are absorbed automatically.',
    )
