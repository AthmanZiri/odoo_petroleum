

from . import models
from . import controllers
from . import wizard

# Menus from dynamic_accounts_report that duplicate interactive account_reports.
_DYNAMIC_DUPLICATE_MENU_XMLIDS = (
    'dynamic_accounts_report.menu_profit_and_loss_report',
    'dynamic_accounts_report.menu_balance_sheet_report',
    'dynamic_accounts_report.menu_general_ledger',
    'dynamic_accounts_report.menu_trial_balance',
    'dynamic_accounts_report.menu_partner_ledger',
    'dynamic_accounts_report.aged_receivable_menu',
    'dynamic_accounts_report.aged_payable_menu',
    'dynamic_accounts_report.tax_report_menu',
)


def _hide_duplicate_dynamic_report_menus(env):
    """Soft-disable overlapping dynamic report menus when that module is installed."""
    for xmlid in _DYNAMIC_DUPLICATE_MENU_XMLIDS:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.active = False


def _account_reports_post_init(env):
    env.ref('account_reports.ir_cron_generate_account_return')._trigger()

    companies = env['res.company'].search([])
    return_types = env['account.return.type'].search([])

    for company in companies:
        for return_type in return_types.with_company(company):
            return_type.deadline_periodicity = return_type.deadline_periodicity or return_type.default_deadline_periodicity
            return_type.deadline_start_date = return_type.deadline_start_date or return_type.default_deadline_start_date

    for company in env['res.company'].search([('chart_template', '!=', False)], order='parent_path'):
        ChartTemplate = env['account.chart.template'].with_company(company)
        # Set up the tax returns journal after the CoA was already installed.
        ChartTemplate._load_data({
            'account.journal': ChartTemplate._get_account_reports_journal(company.chart_template),
            'res.company': ChartTemplate._get_account_reports_res_company(company.chart_template),
        })

    _hide_duplicate_dynamic_report_menus(env)
