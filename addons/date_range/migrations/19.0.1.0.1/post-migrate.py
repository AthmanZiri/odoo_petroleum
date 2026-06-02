from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Fix cron job model: was incorrectly set to res.partner, must be date.range.type."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref("date_range.ir_cron_autocreate", raise_if_not_found=False)
    if not cron:
        return
    date_range_type_model = env["ir.model"].search(
        [("model", "=", "date.range.type")], limit=1
    )
    if date_range_type_model and cron.model_id != date_range_type_model:
        cron.model_id = date_range_type_model
