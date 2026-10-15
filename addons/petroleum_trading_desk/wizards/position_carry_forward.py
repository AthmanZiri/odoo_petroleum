from odoo import api, fields, models


class PetroleumDailyPositionCarryForward(models.TransientModel):
    _name = 'petroleum.daily.position.carry.forward'
    _description = 'Carry Daily Position Forward'

    target_date = fields.Date(
        string='Carry Forward To', required=True,
        default=fields.Date.context_today)
    line_ids = fields.One2many(
        'petroleum.daily.position.carry.forward.line', 'wizard_id',
        string='Lots')

    @api.model
    def _lot_vals(self, lot):
        """Values copied onto a wizard row so the dialog can show and edit them."""
        return {
            'position_line_id': lot.id,
            'date': lot.date,
            'product_id': lot.product_id.id,
            'supplier_id': lot.supplier_id.id,
            'depot_id': lot.depot_id.id,
            'qty_remaining': lot.qty_remaining,
            'quantity': lot.qty_remaining,
        }

    @api.model
    def _line_commands(self, target_date):
        lines = self.env['petroleum.daily.position.line']._carry_forward_candidates(
            target_date)
        return [(0, 0, self._lot_vals(line)) for line in lines]

    def _new_lines(self, target_date):
        """In-memory rows for the dialog. Assigning these from onchange keeps
        every column, including the editable quantity, on the form.
        """
        Line = self.env['petroleum.daily.position.carry.forward.line']
        lines = Line.browse()
        for lot in self.env['petroleum.daily.position.line']._carry_forward_candidates(
                target_date):
            lines |= Line.new(self._lot_vals(lot))
        return lines

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'line_ids' in fields_list and not res.get('line_ids'):
            target = res.get('target_date') or fields.Date.context_today(self)
            res['line_ids'] = self._line_commands(target)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'line_ids' not in vals:
                target = vals.get('target_date') or fields.Date.context_today(self)
                vals['line_ids'] = self._line_commands(target)
        return super().create(vals_list)

    @api.onchange('target_date')
    def _onchange_target_date(self):
        """Reload lots when the date changes. Each row keeps an editable quantity."""
        self.line_ids = self._new_lines(self.target_date)

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
    date = fields.Date(readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    supplier_id = fields.Many2one('res.partner', string='Supplier', readonly=True)
    depot_id = fields.Many2one('petroleum.depot', string='Depot', readonly=True)
    qty_remaining = fields.Float(
        string='Remaining', readonly=True, digits='Product Unit of Measure')
    quantity = fields.Float(
        string='Quantity to carry', digits='Product Unit of Measure')
