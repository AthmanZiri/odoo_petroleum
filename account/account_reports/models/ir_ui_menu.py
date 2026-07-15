from odoo import api, models

# Kept in sync with account_reports/__init__.py::_DYNAMIC_DUPLICATE_MENU_XMLIDS
_DYNAMIC_DUPLICATE_MENU_XMLIDS = (
    'dynamic_accounts_report.menu_profit_and_loss_report',
    'dynamic_accounts_report.menu_balance_sheet_report',
    'dynamic_accounts_report.menu_general_ledger',
    'dynamic_accounts_report.menu_trial_balance',
    'dynamic_accounts_report.menu_partner_ledger',
    'dynamic_accounts_report.aged_receivable_menu',
    'dynamic_accounts_report.aged_payable_menu',
    'dynamic_accounts_report.tax_report_menu',
    'dynamic_accounts_report.menu_bank_book',
    'dynamic_accounts_report.menu_cash_book',
)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _get_account_readonly_menu_ids(self):
        res = super()._get_account_readonly_menu_ids()
        res.extend([
            'account_reports.menu_action_account_report_multicurrency_revaluation',
            'account_reports.menu_action_account_report_tree',
        ])
        return res

    @api.model
    def _account_reports_hide_duplicate_dynamic_menus(self):
        """Called from data XML so duplicates stay hidden after module upgrades."""
        for xmlid in _DYNAMIC_DUPLICATE_MENU_XMLIDS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                menu.active = False
