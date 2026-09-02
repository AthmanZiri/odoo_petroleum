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
        self.affected_quantity = (
            self.qty_sold if self.volume_scope == 'sold' else self.qty_remaining)
        if self.volume_scope == 'sold':
            self._populate_sold_lines()
        else:
            self.line_ids = [fields.Command.clear()]
            self.recommendation_note = False

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
        'volume_scope', 'line_ids.selected', 'line_ids.affected_quantity',
        'line_ids.buy_price',
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
                wiz.credit_amount = amount
                wiz.price_drop = amount / affected if affected else 0.0
                continue
            change = abs(wiz.current_buy_price - wiz.new_buy_price)
            wiz.price_drop = change
            wiz.credit_amount = change * wiz.affected_quantity

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
        line = self.position_line_id
        if not line:
            raise UserError(_('Select a position lot to revise.'))
        rounding = self._qty_rounding()
        available = self.qty_sold if self.volume_scope == 'sold' else self.qty_remaining
        if self.affected_quantity <= 0 or self.affected_quantity > available:
            raise UserError(_(
                'Affected litres must be greater than zero and cannot exceed %s L.',
                available,
            ))
        if self.volume_scope == 'sold':
            if not self.line_ids:
                self._populate_sold_lines()
            if (
                self._sold_lines_are_default_all()
                and float_compare(
                    self.affected_quantity, self.qty_sold,
                    precision_rounding=rounding) < 0
            ):
                self._apply_sold_recommendation()
            selected = self.line_ids.filtered(
                lambda row: row.selected and row.affected_quantity > 0
                and not line._same_price_values(
                    row.buy_price, self.new_buy_price))
            if not selected:
                raise UserError(_('Select at least one deal to revise.'))
            allocation_quantities = {
                row.allocation_id.id: row.affected_quantity for row in selected}
            quantity = sum(allocation_quantities.values())
            moves = line.action_create_sold_price_adjustments(
                self.new_buy_price, quantity, self.note,
                allocation_quantities=allocation_quantities)
            if len(moves) == 1:
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Supplier Price Adjustment'),
                    'res_model': 'account.move',
                    'res_id': moves.id,
                    'view_mode': 'form',
                    'target': 'current',
                }
            return {
                'type': 'ir.actions.act_window',
                'name': _('Supplier Price Adjustments'),
                'res_model': 'account.move',
                'domain': [('id', 'in', moves.ids)],
                'view_mode': 'list,form',
                'target': 'current',
            }

        result = line.action_revise_buy_price(
            new_buy_price=self.new_buy_price,
            note=self.note,
            merge_into_matching=self.merge_into_matching,
            create_credit_note=self.create_credit_note,
            affected_quantity=self.affected_quantity,
        )
        credit = result['credit_note']
        if credit:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Supplier Price Adjustment'),
                'res_model': 'account.move',
                'res_id': credit.id,
                'view_mode': 'form',
                'target': 'current',
            }
        surviving = result['surviving_line']
        if result['merged']:
            message = _(
                'Revised %(qty)s L from %(old)s to %(new)s and merged into the '
                'existing @%(new)s lot.',
                qty=result['transferred_qty'],
                old=result['old_price'],
                new=result['new_price'],
            )
        else:
            message = _(
                'Buy price revised from %(old)s to %(new)s on %(qty)s L remaining.',
                old=result['old_price'],
                new=result['new_price'],
                qty=result['transferred_qty'],
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Buy price revised'),
                'message': message,
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
    split_hint = fields.Char(compute='_compute_split_hint')
    is_split = fields.Boolean(compute='_compute_split_hint')

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
