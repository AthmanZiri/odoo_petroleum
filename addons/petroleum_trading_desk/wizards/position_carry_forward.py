from odoo import api, fields, models


class PetroleumDailyPositionCarryForward(models.TransientModel):
    _name = 'petroleum.daily.position.carry.forward'
    _description = 'Carry Daily Position Forward'

    target_date = fields.Date(
        string='Carry Forward To', required=True,
        default=fields.Date.context_today)
    restrict_line_ids = fields.Many2many(
        'petroleum.daily.position.line',
        'petroleum_carry_forward_lot_rel',
        'wizard_id', 'position_line_id',
        string='Selected Lots',
        help='When set, only these lots are offered. Empty means every '
             'earlier unrolled lot with remaining stock.')
    line_ids = fields.One2many(
        'petroleum.daily.position.carry.forward.line', 'wizard_id',
        string='Lots')
    qty_to_carry = fields.Float(
        string='Quantity to carry', compute='_compute_qty_to_carry',
        digits='Product Unit of Measure')

    @api.depends('line_ids.quantity')
    def _compute_qty_to_carry(self):
        for wizard in self:
            wizard.qty_to_carry = sum(wizard.line_ids.mapped('quantity'))

    @api.model
    def _line_commands(self, target_date, restrict_ids=None):
        lines = self.env['petroleum.daily.position.line']._carry_forward_candidates(
            target_date, restrict_ids=restrict_ids)
        return [
            (0, 0, {
                'position_line_id': line.id,
                'quantity': line.qty_remaining,
            })
            for line in lines
        ]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get('carry_forward_line_ids') or []
        if ids and 'restrict_line_ids' in fields_list:
            res['restrict_line_ids'] = [(6, 0, list(ids))]
        if 'line_ids' in fields_list and not res.get('line_ids'):
            target = res.get('target_date') or fields.Date.context_today(self)
            res['line_ids'] = self._line_commands(target, ids or None)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        context_ids = self.env.context.get('carry_forward_line_ids') or []
        Position = self.env['petroleum.daily.position.line']
        for vals in vals_list:
            if context_ids and 'restrict_line_ids' not in vals:
                vals['restrict_line_ids'] = [(6, 0, list(context_ids))]
            if 'line_ids' not in vals:
                target = vals.get('target_date') or fields.Date.context_today(self)
                vals['line_ids'] = [
                    (0, 0, {
                        'position_line_id': line.id,
                        'quantity': line.qty_remaining,
                    })
                    for line in Position._carry_forward_candidates(
                        target, restrict_ids=context_ids or None)
                ]
        return super().create(vals_list)

    @api.onchange('target_date')
    def _onchange_target_date(self):
        """Reload the lot list for the new date. Edited quantities are reset."""
        restrict_ids = None
        if self.restrict_line_ids:
            restrict_ids = self.restrict_line_ids.ids
        elif self.env.context.get('carry_forward_line_ids'):
            restrict_ids = list(self.env.context['carry_forward_line_ids'])
        self.line_ids = [(5, 0, 0)] + self._line_commands(
            self.target_date, restrict_ids)

    def action_confirm(self):
        self.ensure_one()
        quantities = {
            line.position_line_id.id: line.quantity
            for line in self.line_ids
            if line.position_line_id
        }
        return self.env['petroleum.daily.position.line']._carry_forward_to(
            self.target_date, quantities=quantities)


class PetroleumDailyPositionCarryForwardLine(models.TransientModel):
    _name = 'petroleum.daily.position.carry.forward.line'
    _description = 'Carry Forward Lot'

    wizard_id = fields.Many2one(
        'petroleum.daily.position.carry.forward', required=True,
        ondelete='cascade')
    position_line_id = fields.Many2one(
        'petroleum.daily.position.line', string='Position Lot', required=True,
        ondelete='cascade')
    date = fields.Date(related='position_line_id.date')
    product_id = fields.Many2one(related='position_line_id.product_id')
    supplier_id = fields.Many2one(related='position_line_id.supplier_id')
    depot_id = fields.Many2one(related='position_line_id.depot_id')
    qty_remaining = fields.Float(
        related='position_line_id.qty_remaining', string='Remaining',
        digits='Product Unit of Measure')
    quantity = fields.Float(
        string='Quantity to carry', required=True,
        digits='Product Unit of Measure')
