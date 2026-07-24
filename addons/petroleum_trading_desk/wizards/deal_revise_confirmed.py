from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class PetroleumDealReviseConfirmed(models.TransientModel):
    _name = 'petroleum.deal.revise.confirmed'
    _description = 'Revise Confirmed Deal'

    deal_id = fields.Many2one(
        'petroleum.deal', required=True, ondelete='cascade')
    deal_line_id = fields.Many2one(
        'petroleum.deal.line', string='Deal Line', required=True,
        domain="[('deal_id', '=', deal_id)]")
    product_id = fields.Many2one(related='deal_line_id.product_id')
    currency_id = fields.Many2one(related='deal_id.currency_id')
    current_quantity = fields.Float(
        string='Current Litres', readonly=True,
        digits='Product Unit of Measure')
    current_sell_price = fields.Float(
        string='Current Sell Price', readonly=True, digits='Product Price')
    new_quantity = fields.Float(
        string='New Litres', required=True, digits='Product Unit of Measure')
    new_sell_price = fields.Float(
        string='New Sell Price', required=True, digits='Product Price')
    note = fields.Char(
        string='Reason / Note', required=True,
        default='Confirmed deal correction')

    @api.onchange('deal_line_id')
    def _onchange_deal_line_id(self):
        if not self.deal_line_id:
            return
        self.current_quantity = self.deal_line_id.quantity
        self.current_sell_price = self.deal_line_id.sell_price
        self.new_quantity = self.deal_line_id.quantity
        self.new_sell_price = self.deal_line_id.sell_price

    def _qty_compare(self, first, second):
        self.ensure_one()
        rounding = self.product_id.uom_id.rounding if self.product_id.uom_id else 0.01
        return float_compare(first, second, precision_rounding=rounding)

    def _price_compare(self, first, second):
        self.ensure_one()
        precision = self.currency_id.decimal_places if self.currency_id else 2
        return float_compare(first, second, precision_digits=precision)

    def _find_sale_order_line(self):
        self.ensure_one()
        line = self.deal_line_id
        order = self.deal_id.sale_order_id
        if not order:
            raise UserError(_('This confirmed deal has no linked sale order.'))
        candidates = order.order_line.filtered(
            lambda so_line: so_line.product_id == line.product_id
            and not so_line.display_type)
        if len(candidates) == 1:
            return candidates
        candidates = candidates.filtered(
            lambda so_line: so_line.petro_supplier_id == line.supplier_id)
        if len(candidates) == 1:
            return candidates
        candidates = candidates.filtered(
            lambda so_line: self._price_compare(
                so_line.petro_buy_price, line.buy_price) == 0)
        if len(candidates) == 1:
            return candidates
        candidates = candidates.filtered(
            lambda so_line: self._qty_compare(
                so_line.product_uom_qty, line.quantity) == 0)
        if len(candidates) == 1:
            return candidates
        raise UserError(_(
            'Could not identify the sale order line for %(product)s. '
            'Revise the sale order manually or split duplicate products first.',
            product=line.product_id.display_name,
        ))

    def _check_not_invoiced(self, sale_line):
        self.ensure_one()
        posted = self.deal_id.invoice_ids.filtered(
            lambda move: move.move_type in ('out_invoice', 'out_refund')
            and move.state == 'posted')
        if posted:
            raise UserError(_(
                'This deal already has a posted customer invoice. Use credit/debit '
                'notes for invoiced quantity changes, or Revise Sell Price for '
                'price-only adjustments.'))
        invoice_lines = sale_line.invoice_lines.filtered(
            lambda inv_line: inv_line.move_id.state != 'cancel')
        if invoice_lines:
            raise UserError(_(
                'This sale order line is already linked to an invoice. Cancel the '
                'draft invoice before revising the confirmed deal.'))

    def _update_position_allocation(self):
        self.ensure_one()
        line = self.deal_line_id
        delta = self.new_quantity - line.quantity
        if self._qty_compare(delta, 0.0) == 0:
            return

        Allocation = self.env['petroleum.daily.position.allocation']
        active_allocs = self.deal_id.position_allocation_ids.filtered(
            lambda alloc: alloc.deal_line_id == line and alloc.state == 'active'
        ).sorted('id')
        if delta > 0:
            pos_line = (
                active_allocs[:1].position_line_id
                or line.position_line_id
                or self.env['petroleum.daily.position.line'].find_for_deal_line(line)
            )
            if not pos_line:
                raise UserError(_(
                    'No daily position lot is available for %(product)s.',
                    product=line.product_id.display_name,
                ))
            if self._qty_compare(pos_line.qty_remaining, delta) < 0:
                raise UserError(_(
                    'Not enough remaining volume on %(lot)s: %(need)s L needed, '
                    '%(left)s L available.',
                    lot=pos_line.display_name,
                    need=delta,
                    left=pos_line.qty_remaining,
                ))
            if active_allocs:
                active_allocs[0].write({
                    'quantity': active_allocs[0].quantity + delta,
                    'buy_price': line.buy_price or pos_line.buy_price,
                })
            else:
                Allocation.create({
                    'position_line_id': pos_line.id,
                    'deal_id': self.deal_id.id,
                    'deal_line_id': line.id,
                    'quantity': self.new_quantity,
                    'buy_price': line.buy_price or pos_line.buy_price,
                })
                if not line.position_line_id:
                    line.position_line_id = pos_line
            return

        reduction = abs(delta)
        if self._qty_compare(sum(active_allocs.mapped('quantity')), reduction) < 0:
            raise UserError(_(
                'The active position allocation is smaller than the requested '
                'quantity reduction.'))
        remaining = reduction
        for alloc in active_allocs.sorted('id', reverse=True):
            if self._qty_compare(remaining, 0.0) <= 0:
                break
            if self._qty_compare(remaining, alloc.quantity) >= 0:
                remaining -= alloc.quantity
                alloc.write({'state': 'released'})
            else:
                alloc.write({'quantity': alloc.quantity - remaining})
                remaining = 0.0

    def action_confirm(self):
        self.ensure_one()
        deal = self.deal_id
        line = self.deal_line_id
        if deal.state != 'confirmed':
            raise UserError(_(
                'Only deals in Confirmed status can be revised with this action.'))
        if self.new_quantity <= 0:
            raise UserError(_('New litres must be greater than zero.'))
        same_qty = self._qty_compare(self.new_quantity, line.quantity) == 0
        same_price = self._price_compare(self.new_sell_price, line.sell_price) == 0
        if same_qty and same_price:
            raise UserError(_('Enter a new quantity or sell price to revise.'))

        sale_line = self._find_sale_order_line()
        self._check_not_invoiced(sale_line)
        old_quantity = line.quantity
        old_price = line.sell_price

        self._update_position_allocation()
        line.write({
            'quantity': self.new_quantity,
            'sell_price': self.new_sell_price,
        })
        sale_line.write({
            'product_uom_qty': self.new_quantity,
            'price_unit': self.new_sell_price,
            'petro_supplier_id': line.supplier_id.id,
            'petro_buy_price': line.buy_price,
        })

        deal.message_post(body=_(
            'Confirmed deal revised for %(product)s: %(old_qty)s L @ %(old_price)s '
            '→ %(new_qty)s L @ %(new_price)s. %(note)s',
            product=line.product_id.display_name,
            old_qty=old_quantity,
            old_price=old_price,
            new_qty=self.new_quantity,
            new_price=self.new_sell_price,
            note=self.note,
        ))
        return {'type': 'ir.actions.act_window_close'}
