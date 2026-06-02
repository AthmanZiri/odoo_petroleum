from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    petro_import_batch = fields.Char(
        string='Petroleum Import Batch', index=True, copy=False,
        help='Tags journal entries / invoices created by the Petroleum Data Import '
             'wizard so a batch can be identified and rolled back.')
