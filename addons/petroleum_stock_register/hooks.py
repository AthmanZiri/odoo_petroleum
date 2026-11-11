def post_init_hook(env):
    """Fresh installs arm the register and create its warehouse. Quantities stay at zero."""
    companies = env['res.company'].search([])
    companies._petro_try_arm_stock_register()
    companies._petro_ensure_register_warehouse()
