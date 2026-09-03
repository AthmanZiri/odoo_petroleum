def post_init_hook(env):
    """Open cash books for Bank and Cash accounts created before this module."""
    env['account.account'].search([
        ('account_type', '=', 'asset_cash'),
        ('active', '=', True),
    ])._petroleum_ensure_bank_journals()
