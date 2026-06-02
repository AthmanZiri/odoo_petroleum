def post_init_hook(env):
    """Remove the legacy scheduled statement cron if it exists from an older install."""
    env['ir.cron'].search([
        ('name', '=', 'Email Daily Customer Statements'),
    ]).unlink()
