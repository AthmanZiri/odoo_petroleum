from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.account'].search([
        ('account_type', '=', 'asset_cash'),
        ('active', '=', True),
    ])._petroleum_ensure_bank_journals()
