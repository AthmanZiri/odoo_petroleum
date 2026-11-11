def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.company'].search([])._petro_ensure_register_warehouse()
