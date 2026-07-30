from odoo import api, models


class AccountAccount(models.Model):
    _inherit = 'account.account'

    @api.model
    def _petroleum_account_codes(self, account):
        """Normalize account codes whether code_store is a dict or a string."""
        codes = []
        code = getattr(account, 'code', None)
        if code:
            codes.append(str(code))
        store = account.code_store
        if isinstance(store, dict):
            codes.extend(str(v) for v in store.values() if v)
        elif store:
            codes.append(str(store))
        return codes

    @api.model
    def _petroleum_reclassify_purchase_cost_accounts(self):
        """Ensure purchase / COGS accounts feed Cost of Sales on the P&amp;L."""
        accounts = self.sudo().search([('account_type', '=', 'expense')])
        to_fix = self.env['account.account']
        for acc in accounts:
            codes = self._petroleum_account_codes(acc)
            name = acc.with_context(lang='en_US').name or ''
            name_u = name.upper() if isinstance(name, str) else str(name).upper()
            if '500100' in codes or name_u == 'DIRECT EXPENSE':
                to_fix |= acc
            elif 'COST OF SALES' in name_u and 'VARIATION' not in name_u:
                to_fix |= acc
        if to_fix:
            to_fix.write({'account_type': 'expense_direct_cost'})
        return True
