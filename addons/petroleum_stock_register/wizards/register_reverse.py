from odoo import fields, models


class PetroleumStockRegisterReverse(models.TransientModel):
    _name = 'petroleum.stock.register.reverse'
    _description = 'Reverse Petroleum Stock Register'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )

    def action_reverse(self):
        """Post the opposite of every register move and stop following the board."""
        self.ensure_one()
        company = self.company_id
        moves = self.env['stock.move'].search([
            ('company_id', '=', company.id),
            ('petro_register', '=', True),
            ('state', '=', 'done'),
            ('petro_reversal_of_id', '=', False),
            ('petro_reversal_move_id', '=', False),
        ])
        today = fields.Date.context_today(self)
        for move in moves:
            reversal = self.env['stock.move']._petro_post_register_move(
                move.product_id,
                move.location_dest_id,
                move.location_id,
                move.quantity,
                company,
                'Register reversal',
                today,
            )
            if reversal:
                move.petro_reversal_move_id = reversal.id
                reversal.petro_reversal_of_id = move.id
        self.env['petroleum.stock.register.hint'].search([
            ('company_id', '=', company.id),
            ('state', '=', 'pending'),
        ]).write({
            'state': 'applied',
            'note': 'Cleared when the register was reversed.',
        })
        company.write({
            'petro_stock_register_mode': 'armed',
            'petro_stock_register_open_date': False,
        })
        return {'type': 'ir.actions.act_window_close'}
