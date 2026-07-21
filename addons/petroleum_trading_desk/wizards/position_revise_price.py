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

    @api.onchange('position_line_id', 'volume_scope')
    def _onchange_volume_scope(self):
        if not self.position_line_id:
            return
        self.affected_quantity = (
            self.qty_sold if self.volume_scope == 'sold' else self.qty_remaining)

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
        'volume_scope', 'position_line_id.allocation_ids.quantity',
        'position_line_id.allocation_ids.buy_price',
        'position_line_id.allocation_ids.state')
    def _compute_credit(self):
        for wiz in self:
            if wiz.volume_scope == 'sold' and wiz.position_line_id:
                left = wiz.affected_quantity
                amount = 0.0
                allocations = wiz.position_line_id.allocation_ids.filtered(
                    lambda allocation: allocation.state == 'active'
                    and not wiz.position_line_id._same_price_values(
                        allocation.buy_price, wiz.new_buy_price)
                ).sorted('id')
                for allocation in allocations:
                    if left <= 0:
                        break
                    affected = min(left, allocation.quantity)
                    amount += abs(
                        allocation.buy_price - wiz.new_buy_price) * affected
                    left -= affected
                wiz.credit_amount = amount
                wiz.price_drop = (
                    amount / wiz.affected_quantity
                    if wiz.affected_quantity else 0.0)
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
        available = self.qty_sold if self.volume_scope == 'sold' else self.qty_remaining
        if self.affected_quantity <= 0 or self.affected_quantity > available:
            raise UserError(_(
                'Affected litres must be greater than zero and cannot exceed %s L.',
                available,
            ))
        if self.volume_scope == 'sold':
            moves = line.action_create_sold_price_adjustments(
                self.new_buy_price, self.affected_quantity, self.note)
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

        if self.affected_quantity != self.qty_remaining:
            raise UserError(_(
                'Remaining-stock revisions currently apply to the full remaining '
                'lot (%s L). Use the sold-volume option for a partial adjustment.',
                self.qty_remaining,
            ))
        result = line.action_revise_buy_price(
            new_buy_price=self.new_buy_price,
            note=self.note,
            merge_into_matching=self.merge_into_matching,
            create_credit_note=self.create_credit_note,
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
