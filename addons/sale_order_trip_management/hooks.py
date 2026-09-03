def post_init_hook(env):
    env['res.company'].search([])._petroleum_ensure_staff_claims_journal()
