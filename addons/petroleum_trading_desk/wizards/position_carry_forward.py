from odoo import api, fields, models, _


class PetroleumDailyPositionCarryForward(models.TransientModel):
    _name = 'petroleum.daily.position.carry.forward'
    _description = 'Carry Daily Position Forward'

    target_date = fields.Date(
        string='Carry Forward To', required=True,
        default=fields.Date.context_today)
    source_line_ids = fields.Many2many(
        'petroleum.daily.position.line',
        'petroleum_cf_src_lot_rel', 'wizard_id', 'line_id',
        string='Selected Lots',
        help='Rows ticked on Daily Position. Their dates are the only '
             'source dates offered.')
    line_ids = fields.One2many(
        'petroleum.daily.position.carry.forward.line', 'wizard_id',
        string='Lots')
    notice = fields.Char(readonly=True)

    def _selected_lines(self, lines=None):
        """Position rows whose dates limit the dialog. Empty means no limit."""
        if lines is not None:
            return lines
        if self.source_line_ids:
            return self.source_line_ids
        ids = self.env.context.get('carry_forward_line_ids')
        if not ids:
            return self.env['petroleum.daily.position.line']
        return self.env['petroleum.daily.position.line'].browse(ids).exists()

    def _source_dates(self, lines=None):
        selected = self._selected_lines(lines)
        if not selected:
            return None
        return list(set(selected.mapped('date')))

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

    def _candidates(self, target_date, lines=None):
        return self.env['petroleum.daily.position.line']._carry_forward_candidates(
            target_date, source_dates=self._source_dates(lines))

    def _line_commands(self, target_date, lines=None):
        return [(0, 0, self._lot_vals(lot)) for lot in self._candidates(target_date, lines)]

    def _new_lines(self, target_date, lines=None):
        """In-memory rows for the dialog. Assigning these from onchange keeps
        every column, including the editable quantity, on the form.
        """
        Line = self.env['petroleum.daily.position.carry.forward.line']
        rows = Line.browse()
        for lot in self._candidates(target_date, lines):
            rows |= Line.new(self._lot_vals(lot))
        return rows

    def _notice_for(self, target_date, lines=None):
        """Explain an empty list without substituting another day's stock."""
        selected = self._selected_lines(lines)
        if not selected or not target_date or self._candidates(target_date, selected):
            return False
        dates = sorted(set(selected.mapped('date')))
        src = ', '.join(fields.Date.to_string(day) for day in dates)
        lots = self.env['petroleum.daily.position.line'].search([
            ('date', 'in', dates),
        ])
        rolled = lots.filtered(
            lambda lot: lot.date < target_date and lot.rolled_forward_on)
        if rolled:
            dests = ', '.join(sorted({
                fields.Date.to_string(day) for day in rolled.mapped('rolled_forward_on')
            }))
            return _('%(src)s was already carried forward to %(dest)s.',
                     src=src, dest=dests)
        if lots.filtered(lambda lot: lot.date >= target_date) and not lots.filtered(
                lambda lot: lot.date < target_date):
            return _('Carry Forward To must be after %s.', src)
        return _('%s has no remaining litres to carry.', src)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get('carry_forward_line_ids') or []
        lines = self.env['petroleum.daily.position.line'].browse(ids).exists()
        if lines and 'source_line_ids' in fields_list:
            res['source_line_ids'] = [(6, 0, lines.ids)]
        target = res.get('target_date') or fields.Date.context_today(self)
        if 'line_ids' in fields_list and not res.get('line_ids'):
            res['line_ids'] = self._line_commands(target, lines)
        if 'notice' in fields_list and not res.get('notice'):
            res['notice'] = self._notice_for(target, lines) or False
        return res

    @api.model_create_multi
    def create(self, vals_list):
        Position = self.env['petroleum.daily.position.line']
        context_ids = self.env.context.get('carry_forward_line_ids') or []
        for vals in vals_list:
            if context_ids and 'source_line_ids' not in vals:
                vals['source_line_ids'] = [(6, 0, list(context_ids))]
            lines = Position.browse(context_ids).exists() if context_ids else Position
            if 'line_ids' not in vals:
                target = vals.get('target_date') or fields.Date.context_today(self)
                vals['line_ids'] = self._line_commands(target, lines)
                vals.setdefault('notice', self._notice_for(target, lines) or False)
        return super().create(vals_list)

    @api.onchange('target_date')
    def _onchange_target_date(self):
        """Keep the selected source dates and drop lots the destination has reached."""
        self.line_ids = self._new_lines(self.target_date)
        self.notice = self._notice_for(self.target_date)

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
