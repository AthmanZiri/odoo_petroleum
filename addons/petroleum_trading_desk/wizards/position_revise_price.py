from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class PetroleumDailyPositionRevisePrice(models.TransientModel):
    _name = 'petroleum.daily.position.revise.price'
    _description = 'Revise Daily Position Buy Price'

    position_line_id = fields.Many2one(
        'petroleum.daily.position.line', string='Position Lot', required=True,
        ondelete='cascade')
    product_id = fields.Many2one(related='position_line_id.product_id')
    supplier_id = fields.Many2one(related='position_line_id.supplier_id')
    date = fields.Date(related='position_line_id.date')
    currency_id = fields.Many2one(related='position_line_id.currency_id')
    current_buy_price = fields.Float(
        related='position_line_id.buy_price', string='Current Buy Price')
    qty_remaining = fields.Float(
        related='position_line_id.qty_remaining', string='Remaining Litres')
    qty_sold = fields.Float(
        related='position_line_id.qty_sold', string='Sold Litres')
    volume_scope = fields.Selection([
        ('remaining', 'Remaining Stock'),
        ('sold', 'Already Sold / Invoiced'),
    ], string='Apply To', required=True, default='remaining')
    affected_quantity = fields.Float(
        string='Affected Litres', required=True,
        digits='Product Unit of Measure')
    new_buy_price = fields.Float(
        string='New Buy Price', digits='Product Price', required=True)
    revise_lot_quantity = fields.Boolean(
        string='Correct Lot Litres', default=False,
        help='Also correct the litres on this lot (e.g. the supplier '
             'delivered more or fewer litres than recorded).')
    new_lot_quantity = fields.Float(
        string='New Remaining Litres', digits='Product Unit of Measure',
        help='Corrected remaining litres on this lot. Litres already sold '
             'to deals are not touched — revise those on the Sold scope.')
    price_drop = fields.Float(
        string='Change / Litre', compute='_compute_credit', digits='Product Price')
    credit_amount = fields.Monetary(
        string='Adjustment Amount', compute='_compute_credit',
        currency_field='currency_id')
    matching_lot_id = fields.Many2one(
        'petroleum.daily.position.line', string='Matching Lot',
        compute='_compute_matching_lot')
    merge_into_matching = fields.Boolean(
        string='Merge into matching lot', default=True,
        help='If another same-day lot already exists at the new buy price, '
             'move remaining litres onto that lot.')
    create_credit_note = fields.Boolean(
        string='Create supplier adjustment document', default=True,
        help='Draft a vendor credit note for a reduction or debit bill for an increase.')
    note = fields.Char(
        string='Reason / Note', required=True,
        default='Supplier price reduction on remaining stock')
    recommendation_note = fields.Char(string='Deal Recommendation', readonly=True)
    line_ids = fields.One2many(
        'petroleum.daily.position.revise.price.line', 'wizard_id',
        string='Sold Deals')

    def _qty_rounding(self):
        self.ensure_one()
        if self.position_line_id:
            return self.position_line_id._qty_rounding()
        return 0.01

    def _selected_sold_quantity(self):
        self.ensure_one()
        return sum(
            line.affected_quantity
            for line in self.line_ids
            if line.selected and line.affected_quantity > 0)

    def _sold_lines_are_default_all(self):
        self.ensure_one()
        if not self.line_ids:
            return True
        rounding = self._qty_rounding()
        for line in self.line_ids:
            if not line.selected:
                return False
            if float_compare(
                    line.affected_quantity, line.allocated_quantity,
                    precision_rounding=rounding) != 0:
                return False
        return True

    def _populate_sold_lines(self):
        self.ensure_one()
        self.line_ids = [fields.Command.clear()]
        self.recommendation_note = False
        if self.volume_scope != 'sold' or not self.position_line_id:
            return
        commands = []
        allocations = self.position_line_id.allocation_ids.filtered(
            lambda allocation: allocation.state == 'active').sorted('id')
        for allocation in allocations:
            commands.append(fields.Command.create({
                'allocation_id': allocation.id,
                'selected': True,
                'affected_quantity': allocation.quantity,
                'new_quantity': allocation.quantity,
            }))
        self.line_ids = commands
        self.recommendation_note = _(
            'All sold deals on this lot (%s L). Uncheck deals or type a '
            'target volume to recommend complete deals.',
            self.qty_sold,
        )

    def _apply_sold_recommendation(self):
        self.ensure_one()
        if self.volume_scope != 'sold' or not self.position_line_id:
            return
        if not self.line_ids:
            self._populate_sold_lines()
        rounding = self._qty_rounding()
        target = self.affected_quantity
        allocations = self.line_ids.mapped('allocation_id').filtered(
            lambda allocation: allocation.state == 'active'
            and not self.position_line_id._same_price_values(
                allocation.buy_price, self.new_buy_price))
        if not allocations:
            allocations = self.line_ids.mapped('allocation_id').filtered(
                lambda allocation: allocation.state == 'active')
        try:
            pairs = self.position_line_id._recommend_sold_allocation_quantities(
                allocations, target)
        except UserError as error:
            self.recommendation_note = error.args[0] if error.args else str(error)
            return
        qty_by_alloc = {alloc.id: qty for alloc, qty in pairs}
        split_names = []
        selected_names = []
        for line in self.line_ids:
            qty = qty_by_alloc.get(line.allocation_id.id, 0.0)
            line.selected = float_compare(qty, 0.0, precision_rounding=rounding) > 0
            line.affected_quantity = qty
            if line.selected:
                selected_names.append(line.deal_id.display_name)
                if float_compare(
                        qty, line.allocated_quantity,
                        precision_rounding=rounding) < 0:
                    split_names.append(_(
                        '%(qty)s of %(total)s L on %(deal)s',
                        qty=qty, total=line.allocated_quantity,
                        deal=line.deal_id.display_name,
                    ))
        assigned = sum(qty_by_alloc.values())
        if split_names:
            self.recommendation_note = _(
                'No exact complete-deal match for %(qty)s L. Recommended '
                '%(deals)s, including split: %(split)s.',
                qty=assigned,
                deals=', '.join(selected_names),
                split='; '.join(split_names),
            )
        else:
            self.recommendation_note = _(
                'Recommended complete deals totaling %(qty)s L: %(deals)s.',
                qty=assigned,
                deals=', '.join(selected_names) or '-',
            )

    @api.onchange('position_line_id', 'volume_scope')
    def _onchange_volume_scope(self):
        if not self.position_line_id:
            return
        if self.qty_remaining <= 0:
            self.volume_scope = 'sold'
        self.affected_quantity = (
            self.qty_sold if self.volume_scope == 'sold' else self.qty_remaining)
        self.new_lot_quantity = self.qty_remaining
        if self.volume_scope == 'sold':
            self.revise_lot_quantity = False
            self._populate_sold_lines()
        else:
            self.line_ids = [fields.Command.clear()]
            self.recommendation_note = False

    @api.onchange('revise_lot_quantity')
    def _onchange_revise_lot_quantity(self):
        if self.revise_lot_quantity and self.position_line_id:
            self.new_lot_quantity = self.qty_remaining

    @api.onchange('new_lot_quantity')
    def _onchange_new_lot_quantity(self):
        if (
            self.volume_scope == 'remaining'
            and self.revise_lot_quantity
            and self.new_lot_quantity >= 0
            and self.affected_quantity > self.new_lot_quantity
        ):
            # The price revision can only cover the corrected litres.
            self.affected_quantity = self.new_lot_quantity

    @api.onchange('affected_quantity', 'new_buy_price')
    def _onchange_affected_quantity(self):
        if self.volume_scope != 'sold' or not self.line_ids:
            return
        rounding = self._qty_rounding()
        if float_compare(
                self._selected_sold_quantity(), self.affected_quantity,
                precision_rounding=rounding) == 0:
            return
        self._apply_sold_recommendation()

    @api.onchange('line_ids')
    def _onchange_line_ids(self):
        if self.volume_scope != 'sold':
            return
        selected_qty = self._selected_sold_quantity()
        if selected_qty:
            self.affected_quantity = selected_qty

    @api.depends('position_line_id', 'new_buy_price')
    def _compute_matching_lot(self):
        for wiz in self:
            if wiz.position_line_id and wiz.new_buy_price:
                wiz.matching_lot_id = wiz.position_line_id._find_merge_target(
                    wiz.new_buy_price)
            else:
                wiz.matching_lot_id = False

    @api.depends(
        'current_buy_price', 'new_buy_price', 'affected_quantity', 'currency_id',
        'volume_scope', 'revise_lot_quantity', 'new_lot_quantity',
        'line_ids.selected', 'line_ids.affected_quantity',
        'line_ids.buy_price', 'line_ids.new_quantity',
        'position_line_id.allocation_ids.quantity',
        'position_line_id.allocation_ids.buy_price',
        'position_line_id.allocation_ids.state')
    def _compute_credit(self):
        for wiz in self:
            if wiz.volume_scope == 'sold' and wiz.position_line_id:
                amount = 0.0
                affected = 0.0
                if wiz.line_ids:
                    for line in wiz.line_ids.filtered(
                            lambda row: row.selected and row.affected_quantity > 0):
                        if wiz.position_line_id._same_price_values(
                                line.buy_price, wiz.new_buy_price):
                            continue
                        amount += abs(line.buy_price - wiz.new_buy_price) * line.affected_quantity
                        affected += line.affected_quantity
                else:
                    left = wiz.affected_quantity
                    allocations = wiz.position_line_id.allocation_ids.filtered(
                        lambda allocation: allocation.state == 'active'
                        and not wiz.position_line_id._same_price_values(
                            allocation.buy_price, wiz.new_buy_price)
                    ).sorted('id')
                    try:
                        pairs = wiz.position_line_id._recommend_sold_allocation_quantities(
                            allocations, left)
                    except UserError:
                        pairs = []
                    for allocation, qty in pairs:
                        amount += abs(allocation.buy_price - wiz.new_buy_price) * qty
                        affected += qty
                # Customer-side effect of sold quantity corrections.
                for line in wiz.line_ids:
                    qty_delta = line._quantity_delta()
                    if qty_delta:
                        amount += abs(qty_delta) * (
                            line.allocation_id.deal_line_id.sell_price or 0.0)
                wiz.credit_amount = amount
                wiz.price_drop = amount / affected if affected else 0.0
                continue
            change = abs(wiz.current_buy_price - wiz.new_buy_price)
            amount = change * wiz.affected_quantity
            if wiz.revise_lot_quantity:
                amount += abs(
                    wiz.new_lot_quantity - wiz.qty_remaining
                ) * wiz.current_buy_price
            wiz.price_drop = change
            wiz.credit_amount = amount

    @api.onchange('matching_lot_id')
    def _onchange_matching_lot(self):
        if self.matching_lot_id:
            self.merge_into_matching = True

    @api.onchange('new_buy_price', 'current_buy_price')
    def _onchange_new_price(self):
        if self.new_buy_price and self.current_buy_price:
            precision = (
                self.currency_id.decimal_places if self.currency_id else 2)
            if float_compare(
                    self.current_buy_price, self.new_buy_price,
                    precision_digits=precision) != 0:
                self.create_credit_note = True

    def action_confirm(self):
        self.ensure_one()
        if not self.position_line_id:
            raise UserError(_('Select a position lot to revise.'))
        if self.volume_scope == 'sold':
            return self._confirm_sold()
        return self._confirm_remaining()

    def _action_open_adjustment_moves(self, moves):
        self.ensure_one()
        if len(moves) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Lot Revision Document'),
                'res_model': 'account.move',
                'res_id': moves.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lot Revision Documents'),
            'res_model': 'account.move',
            'domain': [('id', 'in', moves.ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }

    def _confirm_remaining(self):
        self.ensure_one()
        line = self.position_line_id
        rounding = self._qty_rounding()
        qty_revision = self.revise_lot_quantity and float_compare(
            self.new_lot_quantity, line.qty_remaining,
            precision_rounding=rounding) != 0
        price_revision = not line._same_price_values(
            line.buy_price, self.new_buy_price)
        if not qty_revision and not price_revision:
            raise UserError(_(
                'Enter a new buy price or corrected litres to revise.'))

        moves = self.env['account.move']
        messages = []
        if qty_revision:
            qty_result = line.action_revise_lot_quantity(
                self.new_lot_quantity,
                note=self.note,
                create_adjustment_doc=self.create_credit_note,
            )
            moves |= qty_result['adjustment_move']
            messages.append(_(
                'Remaining litres corrected from %(old)s L to %(new)s L%(po)s.',
                old=qty_result['old_remaining'],
                new=qty_result['new_remaining'],
                po=_(' (purchase order and vendor bill re-aligned)')
                if qty_result['po_synced'] else '',
            ))

        result = None
        if price_revision:
            available = line.qty_remaining
            affected = self.affected_quantity
            if qty_revision and float_compare(
                    affected, available, precision_rounding=rounding) > 0:
                affected = available
            if affected <= 0 or float_compare(
                    affected, available, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Affected litres must be greater than zero and cannot '
                    'exceed %s L.',
                    available,
                ))
            result = line.action_revise_buy_price(
                new_buy_price=self.new_buy_price,
                note=self.note,
                merge_into_matching=self.merge_into_matching,
                create_credit_note=self.create_credit_note,
                affected_quantity=affected,
            )
            moves |= result['credit_note']
            if result['merged']:
                messages.append(_(
                    'Revised %(qty)s L from %(old)s to %(new)s and merged into '
                    'the existing @%(new)s lot.',
                    qty=result['transferred_qty'],
                    old=result['old_price'],
                    new=result['new_price'],
                ))
            else:
                messages.append(_(
                    'Buy price revised from %(old)s to %(new)s on %(qty)s L '
                    'remaining.',
                    old=result['old_price'],
                    new=result['new_price'],
                    qty=result['transferred_qty'],
                ))

        if moves:
            return self._action_open_adjustment_moves(moves)
        surviving = result['surviving_line'] if result else line
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Lot revised'),
                'message': ' '.join(messages),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'petroleum.daily.position.line',
                    'res_id': surviving.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'current',
                },
            },
        }

    def _sold_quantity_revision_rows(self):
        """Rows whose New Litres actually change the sold deal quantity."""
        self.ensure_one()
        rounding = self._qty_rounding()
        return self.line_ids.filtered(
            lambda row: float_compare(
                row.new_quantity, 0.0, precision_rounding=rounding) > 0
            and float_compare(
                row.new_quantity, row.allocated_quantity,
                precision_rounding=rounding) != 0)

    def _apply_sold_quantity_revisions(self, qty_rows):
        """Revise deal quantities through the confirmed-deal wizard.

        Reuses ``petroleum.deal.revise.confirmed`` so the deal line, sale
        order line, position allocation, and customer quantity credit/debit
        note all stay consistent. Returns the created draft moves.
        """
        self.ensure_one()
        rounding = self._qty_rounding()
        moves = self.env['account.move']
        deltas = {}
        for row in qty_rows:
            deal_line = row.allocation_id.deal_line_id
            deltas.setdefault(deal_line, 0.0)
            deltas[deal_line] += row.new_quantity - row.allocated_quantity
        for deal_line, delta in deltas.items():
            if float_compare(delta, 0.0, precision_rounding=rounding) == 0:
                continue
            wizard = self.env['petroleum.deal.revise.confirmed'].create({
                'deal_id': deal_line.deal_id.id,
                'deal_line_id': deal_line.id,
                'current_quantity': deal_line.quantity,
                'current_sell_price': deal_line.sell_price,
                'new_quantity': deal_line.quantity + delta,
                'new_sell_price': deal_line.sell_price,
                'note': self.note,
            })
            effective = wizard._effective_sell_price()
            wizard.write({
                'current_sell_price': effective,
                'new_sell_price': effective,
            })
            moves |= wizard._apply_revision()
        return moves

    def _confirm_sold(self):
        self.ensure_one()
        line = self.position_line_id
        rounding = self._qty_rounding()
        if not self.line_ids:
            self._populate_sold_lines()
        qty_rows = self._sold_quantity_revision_rows()
        if (
            not qty_rows
            and self._sold_lines_are_default_all()
            and self.affected_quantity > 0
            and float_compare(
                self.affected_quantity, self.qty_sold,
                precision_rounding=rounding) < 0
        ):
            self._apply_sold_recommendation()
            qty_rows = self._sold_quantity_revision_rows()

        # Snapshot the price selection before litres change: price applies
        # to the litres that remain on each deal after the correction.
        allocation_quantities = {}
        for row in self.line_ids:
            if not row.selected or row.affected_quantity <= 0:
                continue
            if line._same_price_values(row.buy_price, self.new_buy_price):
                continue
            affected = row.affected_quantity
            if row in qty_rows and float_compare(
                    affected, row.new_quantity,
                    precision_rounding=rounding) > 0:
                affected = row.new_quantity
            allocation_quantities[row.allocation_id.id] = affected

        if not qty_rows and not allocation_quantities:
            raise UserError(_('Select at least one deal to revise.'))

        moves = self.env['account.move']
        if qty_rows:
            moves |= self._apply_sold_quantity_revisions(qty_rows)
            # Drop allocations the quantity step released entirely.
            Allocation = self.env['petroleum.daily.position.allocation']
            for alloc_id in list(allocation_quantities):
                allocation = Allocation.browse(alloc_id)
                if allocation.state != 'active':
                    del allocation_quantities[alloc_id]
                    continue
                if float_compare(
                        allocation_quantities[alloc_id], allocation.quantity,
                        precision_rounding=rounding) > 0:
                    allocation_quantities[alloc_id] = allocation.quantity

        if allocation_quantities:
            quantity = sum(allocation_quantities.values())
            moves |= line.action_create_sold_price_adjustments(
                self.new_buy_price, quantity, self.note,
                allocation_quantities=allocation_quantities)

        if moves:
            return self._action_open_adjustment_moves(moves)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Lot revised'),
                'message': _('Sold deal litres corrected.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class PetroleumDailyPositionRevisePriceLine(models.TransientModel):
    _name = 'petroleum.daily.position.revise.price.line'
    _description = 'Revise Buy Price Sold Deal'
    _order = 'deal_id, id'

    wizard_id = fields.Many2one(
        'petroleum.daily.position.revise.price', required=True, ondelete='cascade')
    allocation_id = fields.Many2one(
        'petroleum.daily.position.allocation', required=True, ondelete='cascade')
    deal_id = fields.Many2one(related='allocation_id.deal_id', store=True)
    partner_id = fields.Many2one(
        related='deal_id.partner_id', string='Client')
    allocated_quantity = fields.Float(
        related='allocation_id.quantity', string='Deal Litres')
    buy_price = fields.Float(related='allocation_id.buy_price', string='Buy Price')
    selected = fields.Boolean(string='Revise', default=True)
    affected_quantity = fields.Float(
        string='Affected Litres', digits='Product Unit of Measure')
    new_quantity = fields.Float(
        string='New Litres', digits='Product Unit of Measure',
        help='Corrected litres for this deal. Lower it to return litres to '
             'the lot (a customer credit note is drafted for invoiced '
             'deals); raise it to allocate more remaining stock.')
    split_hint = fields.Char(compute='_compute_split_hint')
    is_split = fields.Boolean(compute='_compute_split_hint')

    def _quantity_delta(self):
        """Signed litres change requested on this sold deal (0 = unchanged)."""
        self.ensure_one()
        rounding = (
            self.allocation_id.product_id.uom_id.rounding
            if self.allocation_id.product_id.uom_id else 0.01)
        if float_compare(
                self.new_quantity, 0.0, precision_rounding=rounding) <= 0:
            return 0.0
        if float_compare(
                self.new_quantity, self.allocated_quantity,
                precision_rounding=rounding) == 0:
            return 0.0
        return self.new_quantity - self.allocated_quantity

    @api.depends('selected', 'affected_quantity', 'allocated_quantity', 'deal_id')
    def _compute_split_hint(self):
        for line in self:
            rounding = (
                line.allocation_id.product_id.uom_id.rounding
                if line.allocation_id.product_id.uom_id else 0.01)
            is_split = bool(
                line.selected
                and float_compare(
                    line.affected_quantity, 0.0, precision_rounding=rounding) > 0
                and float_compare(
                    line.affected_quantity, line.allocated_quantity,
                    precision_rounding=rounding) < 0)
            line.is_split = is_split
            if is_split:
                line.split_hint = _(
                    '%(qty)s of %(total)s L',
                    qty=line.affected_quantity, total=line.allocated_quantity)
            else:
                line.split_hint = False

    @api.onchange('selected')
    def _onchange_selected(self):
        if self.selected and self.affected_quantity <= 0:
            self.affected_quantity = self.allocated_quantity
        if not self.selected:
            self.affected_quantity = 0.0
