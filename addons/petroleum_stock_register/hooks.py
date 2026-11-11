def post_init_hook(env):
    """Fresh installs arm the register when valuation will not post fuel journals."""
    env['res.company'].search([])._petro_try_arm_stock_register()
