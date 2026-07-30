from odoo import api, models


class AccountAccount(models.Model):
    _inherit = 'account.account'

    @api.model
    def _petroleum_reclassify_purchase_cost_accounts(self):
        """Ensure purchase / COGS accounts feed Cost of Sales on the P&amp;L."""
        accounts = self.sudo().search([('account_type', '=', 'expense')])
        to_fix = self.env['account.account']
        for acc in accounts:
            codes = [str(v) for v in (acc.code_store or {}).values()]
            name = acc.with_context(lang='en_US').name or ''
            name_u = name.upper()
            if '500100' in codes or name_u == 'DIRECT EXPENSE':
                to_fix |= acc
            elif 'COST OF SALES' in name_u and 'VARIATION' not in name_u:
                to_fix |= acc
        if to_fix:
            to_fix.write({'account_type': 'expense_direct_cost'})
        return True
