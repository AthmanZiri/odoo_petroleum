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
    notice = fields.Text(readonly=True)

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
    def _lot_vals(self, lot, path=False):
        """Values copied onto a wizard row so the dialog can show and edit them."""
        vals = {
            'position_line_id': lot.id,
            'date': lot.date,
            'product_id': lot.product_id.id,
            'supplier_id': lot.supplier_id.id,
            'depot_id': lot.depot_id.id,
            'qty_remaining': lot.qty_remaining,
            'quantity': lot.qty_remaining,
        }
        if path:
            vals['path'] = path
        return vals

    def _chain_skip_notice(self, live, path):
        label = _('%(product)s / %(supplier)s @ %(price)s',
                  product=live.product_id.display_name,
                  supplier=live.supplier_id.display_name,
                  price=live.buy_price)
        text = _(
            '%(lot)s is already on %(date)s, which is not before Carry Forward To.',
            lot=label, date=fields.Date.to_string(live.date))
        if path:
            text = '%s %s' % (text, path)
        return text

    def _stuck_chain_notice(self, live, path):
        label = _('%(product)s / %(supplier)s @ %(price)s',
                  product=live.product_id.display_name,
                  supplier=live.supplier_id.display_name,
                  price=live.buy_price)
        text = _(
            '%(lot)s is marked carried forward, but the litres are not on '
            'a later lot that can move.',
            lot=label)
        if path:
            text = '%s %s' % (text, path)
        return text

    def _offer_rows(self, target_date, lines=None):
        """Live lots to show, plus a notice for chains that cannot move.

        With no selected date, every earlier unrolled lot is offered. With a
        selected date, each lot on that date is followed to the line that
        still holds the litres. The historical remaining on a rolled row is
        not offered again.
        """
        Position = self.env['petroleum.daily.position.line']
        if not target_date:
            return [], False
        dates = self._source_dates(lines)
        if dates is None:
            return [
                (lot, False) for lot in Position._carry_forward_candidates(target_date)
            ], False
        sources = Position.search([('date', 'in', dates)], order='date, id')
        rows = []
        seen = set()
        skipped = []
        for source in sources:
            live, chain_dates = source._roll_chain()
            if live.id in seen:
                continue
            seen.add(live.id)
            path = False
            if len(chain_dates) > 1:
                path = ' → '.join(
                    fields.Date.to_string(day) for day in chain_dates)
            if live.date >= target_date:
                skipped.append(self._chain_skip_notice(live, path))
                continue
            if live.rolled_forward_on:
                skipped.append(self._stuck_chain_notice(live, path))
                continue
            if live.qty_remaining <= 0:
                continue
            rows.append((live, path))
        notice = '\n'.join(skipped) if skipped else False
        if not notice and not rows:
            src = ', '.join(fields.Date.to_string(day) for day in sorted(set(dates)))
            notice = _('%s has no remaining litres to carry.', src)
        return rows, notice

    def _line_commands(self, target_date, lines=None):
        rows, notice = self._offer_rows(target_date, lines)
        return [(0, 0, self._lot_vals(lot, path)) for lot, path in rows], notice

    def _new_lines(self, target_date, lines=None):
        """In-memory rows for the dialog. Assigning these from onchange keeps
        every column, including the editable quantity, on the form.
        """
        Line = self.env['petroleum.daily.position.carry.forward.line']
        rows, notice = self._offer_rows(target_date, lines)
        recordset = Line.browse()
        for lot, path in rows:
            recordset |= Line.new(self._lot_vals(lot, path))
        return recordset, notice

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get('carry_forward_line_ids') or []
        lines = self.env['petroleum.daily.position.line'].browse(ids).exists()
        if lines and 'source_line_ids' in fields_list:
            res['source_line_ids'] = [(6, 0, lines.ids)]
        target = res.get('target_date') or fields.Date.context_today(self)
        want_lines = 'line_ids' in fields_list and not res.get('line_ids')
        want_notice = 'notice' in fields_list and not res.get('notice')
        if want_lines or want_notice:
            commands, notice = self._line_commands(target, lines)
            if want_lines:
                res['line_ids'] = commands
            if want_notice:
                res['notice'] = notice or False
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
                commands, notice = self._line_commands(target, lines)
                vals['line_ids'] = commands
                vals.setdefault('notice', notice or False)
        return super().create(vals_list)

    @api.onchange('target_date')
    def _onchange_target_date(self):
        """Keep the selected source dates and follow each lot to its live balance."""
        self.line_ids, self.notice = self._new_lines(self.target_date)

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
    path = fields.Char(string='Rolled path', readonly=True)
