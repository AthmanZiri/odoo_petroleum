# -*- coding: utf-8 -*-
"""Install-time fixes for petroleum P&amp;L."""


def post_init_hook(env):
    env['account.account']._petroleum_reclassify_purchase_cost_accounts()
    report = env.ref('account_reports.profit_and_loss', raise_if_not_found=False)
    if not report:
        return
    env['account.report.line'].search([
        ('report_id', '=', report.id),
        ('code', 'in', ('INC', 'OIN', 'OEXP', 'ALLOC', 'NEPAL')),
    ]).unlink()
