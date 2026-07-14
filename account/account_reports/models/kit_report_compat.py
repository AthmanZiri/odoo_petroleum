
"""Compatibility with base_accounting_kit report wizards.

Those wizards use _name + _inherit = 'account.report', so they copy M2M fields
from account.report. Shared relation tables then collide; kit already works
around this for section_report_ids. Mirror that pattern for horizontal groups.
"""
from odoo import fields, models


def _horizontal_group_m2m(relation):
    return fields.Many2many(
        string="Horizontal Groups",
        comodel_name='account.report.horizontal.group',
        relation=relation,
        column1='report_id',
        column2='horizontal_group_id',
    )


class AccountCommonJournalReport(models.TransientModel):
    _inherit = 'account.common.journal.report'

    horizontal_group_ids = _horizontal_group_m2m('acct_cjr_hg_rel')


class AccountCommonAccountReport(models.TransientModel):
    _inherit = 'account.common.account.report'

    horizontal_group_ids = _horizontal_group_m2m('acct_car_hg_rel')


class AccountCommonPartnerReport(models.TransientModel):
    _inherit = 'account.common.partner.report'

    horizontal_group_ids = _horizontal_group_m2m('acct_cpr_hg_rel')


class CashFlowReport(models.TransientModel):
    _inherit = 'cash.flow.report'

    horizontal_group_ids = _horizontal_group_m2m('acct_cfr_hg_rel')


class KitAccountTaxReport(models.TransientModel):
    _inherit = 'kit.account.tax.report'

    horizontal_group_ids = _horizontal_group_m2m('acct_ktr_hg_rel')


class FinancialReport(models.TransientModel):
    _inherit = 'financial.report'

    horizontal_group_ids = _horizontal_group_m2m('acct_fin_hg_rel')


class AccountPrintJournal(models.TransientModel):
    _inherit = 'account.print.journal'

    horizontal_group_ids = _horizontal_group_m2m('acct_pj_hg_rel')


class AccountBalanceReport(models.TransientModel):
    _inherit = 'account.balance.report'

    horizontal_group_ids = _horizontal_group_m2m('acct_bal_hg_rel')


class AccountReportGeneralLedger(models.TransientModel):
    _inherit = 'account.report.general.ledger'

    horizontal_group_ids = _horizontal_group_m2m('acct_gl_hg_rel')


class AccountAgedTrialBalance(models.TransientModel):
    _inherit = 'account.aged.trial.balance'

    horizontal_group_ids = _horizontal_group_m2m('acct_atb_hg_rel')


class AccountReportPartnerLedger(models.TransientModel):
    _inherit = 'account.report.partner.ledger'

    horizontal_group_ids = _horizontal_group_m2m('acct_pl_hg_rel')
