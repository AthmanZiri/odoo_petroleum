from odoo import _, fields, models
from odoo.exceptions import UserError


class PetroleumStockRegisterOpen(models.TransientModel):
    _name = 'petroleum.stock.register.open'
    _description = 'Open Petroleum Stock Register'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )

    def action_open(self):
        self.ensure_one()
        company = self.company_id
        if company.petro_stock_register_open_date:
            raise UserError(_(
                'The stock register for %s is already open.',
                company.display_name,
            ))
        if company.petro_stock_register_mode != 'armed':
            company.action_arm_stock_register()
        if company.petro_stock_register_mode != 'armed':
            raise UserError(_(
                'Arm the stock register before opening it.',
            ))
        company.petro_stock_register_mode = 'live'
        self.env['petroleum.stock.register']._apply_company(company.id, opening=True)
        company.petro_stock_register_open_date = fields.Date.context_today(self)
        return {'type': 'ir.actions.act_window_close'}
