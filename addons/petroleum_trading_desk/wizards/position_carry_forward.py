from odoo import fields, models


class PetroleumDailyPositionCarryForward(models.TransientModel):
    _name = 'petroleum.daily.position.carry.forward'
    _description = 'Carry Daily Position Forward'

    target_date = fields.Date(
        string='Carry Forward To', required=True,
        default=fields.Date.context_today)

    def action_confirm(self):
        self.ensure_one()
        return self.env['petroleum.daily.position.line']._carry_forward_to(
            self.target_date)
