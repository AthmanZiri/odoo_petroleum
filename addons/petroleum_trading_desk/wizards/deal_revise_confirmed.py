from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

_SKIP_DISPLAY = ('line_section', 'line_subsection', 'line_note')


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
    has_posted_invoice = fields.Boolean(
        compute='_compute_has_posted_invoice')
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

    @api.depends(
        'deal_id', 'deal_id.invoice_ids', 'deal_id.invoice_ids.state',
        'deal_id.invoice_ids.move_type')
    def _compute_has_posted_invoice(self):
        for wizard in self:
            wizard.has_posted_invoice = bool(
                wizard._posted_customer_invoices())

    def _posted_customer_invoices(self):
        self.ensure_one()
        if not self.deal_id:
            return self.env['account.move']
        return self.deal_id.invoice_ids.filtered(
            lambda move: move.move_type == 'out_invoice'
            and move.state == 'posted')

    def _qty_compare(self, first, second):
        self.ensure_one()
        rounding = self.product_id.uom_id.rounding if self.product_id.uom_id else 0.01
        return float_compare(first, second, precision_rounding=rounding)

    def _price_compare(self, first, second):
        self.ensure_one()
        precision = self.currency_id.decimal_places if self.currency_id else 2
        return float_compare(first, second, precision_digits=precision)

    def _effective_sell_price(self, line=None):
        self.ensure_one()
        line = line or self.deal_line_id
        if not line:
            return 0.0
        latest = self.env['account.move'].search([
            ('deal_id', '=', self.deal_id.id),
            ('petro_price_adjustment', '=', 'customer_sell'),
            ('state', '=', 'posted'),
        ], order='invoice_date desc, id desc').filtered(
            lambda move: line.product_id in move.invoice_line_ids.product_id)[:1]
        return latest.petro_new_price if latest else line.sell_price

    @api.onchange('deal_line_id')
    def _onchange_deal_line_id(self):
        if not self.deal_line_id:
            return
        effective = self._effective_sell_price()
        self.current_quantity = self.deal_line_id.quantity
        self.current_sell_price = effective
        self.new_quantity = self.deal_line_id.quantity
        self.new_sell_price = effective

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

    def _original_invoice(self):
        self.ensure_one()
        invoices = self._posted_customer_invoices().filtered(
            lambda move: self.product_id in move.invoice_line_ids.product_id)
        if not invoices:
            invoices = self._posted_customer_invoices()
        if not invoices:
            raise UserError(_(
                'No posted customer invoice found for this deal.'))
        return invoices[:1]

    def _product_lines(self, move):
        return move.invoice_line_ids.filtered(
            lambda inv_line: inv_line.product_id == self.product_id
            and inv_line.display_type not in _SKIP_DISPLAY)

    def _net_invoiced_quantity(self):
        """Posted customer litres for this product, excluding price-only notes."""
        self.ensure_one()
        moves = self.deal_id.invoice_ids.filtered(
            lambda move: move.state == 'posted'
            and move.move_type in ('out_invoice', 'out_refund')
            and not move.petro_price_adjustment)
        net = 0.0
        for move in moves:
            sign = 1.0 if move.move_type == 'out_invoice' else -1.0
            net += sign * sum(self._product_lines(move).mapped('quantity'))
        return net

    def _ensure_invoice_revision_allowed(self, sale_line):
        self.ensure_one()
        posted = self._posted_customer_invoices()
        if posted:
            pending = self.env['account.move'].search([
                ('deal_id', '=', self.deal_id.id),
                ('petro_price_adjustment', '=', 'customer_sell'),
                ('state', '=', 'draft'),
            ], limit=1)
            if pending:
                raise UserError(_(
                    'Post or cancel the existing draft price adjustment %s first.',
                    pending.display_name,
                ))
            return True
        invoice_lines = sale_line.invoice_lines.filtered(
            lambda inv_line: inv_line.move_id.state != 'cancel')
        if invoice_lines:
            raise UserError(_(
                'This sale order line is already linked to an invoice. Cancel the '
                'draft invoice before revising the confirmed deal.'))
        return False

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

    def _create_quantity_adjustment_move(self, original, old_quantity, effective_price):
        self.ensure_one()
        delta = self.new_quantity - old_quantity
        if self._qty_compare(delta, 0.0) == 0:
            return self.env['account.move']

        if delta < 0:
            reduction = abs(delta)
            net = self._net_invoiced_quantity()
            # Net still includes the current deal litres on the original invoice.
            if self._qty_compare(reduction, net) > 0:
                raise UserError(_(
                    'Cannot reduce by %(need)s L: only %(net)s L remain invoiced '
                    'for %(product)s after prior quantity credit/debit notes.',
                    need=reduction,
                    net=net,
                    product=self.product_id.display_name,
                ))
            move_type = 'out_refund'
            direction = _('reduction')
        else:
            move_type = 'out_invoice'
            direction = _('increase')

        original_line = self._product_lines(original)[:1]
        taxes = original_line.tax_ids
        qty = abs(delta)
        return self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.deal_id.partner_id.id,
            'company_id': self.deal_id.company_id.id,
            'invoice_date': fields.Date.context_today(self),
            'deal_id': self.deal_id.id,
            'petro_original_move_id': original.id,
            'invoice_origin': original.name,
            'ref': _('Customer quantity %(direction)s — %(deal)s',
                     direction=direction, deal=self.deal_id.name),
            'invoice_line_ids': [fields.Command.create({
                'product_id': self.product_id.id,
                'name': _(
                    'Customer quantity %(direction)s on %(product)s: '
                    '%(old)s L → %(new)s L @ %(price)s. %(note)s',
                    direction=direction,
                    product=self.product_id.display_name,
                    old=old_quantity,
                    new=self.new_quantity,
                    price=effective_price,
                    note=self.note,
                ),
                'quantity': qty,
                'price_unit': effective_price,
                'petro_buy_price': self.deal_line_id.buy_price,
                'tax_ids': [fields.Command.set(taxes.ids)],
                'product_uom_id': self.product_id.uom_id.id,
            })],
        })

    def _create_price_adjustment_move(self, original, effective_price):
        self.ensure_one()
        comparison = self._price_compare(self.new_sell_price, effective_price)
        if comparison == 0:
            return self.env['account.move']

        original_line = self._product_lines(original)[:1]
        taxes = original_line.tax_ids
        delta = abs(self.new_sell_price - effective_price)
        move_type = 'out_invoice' if comparison > 0 else 'out_refund'
        direction = _('increase') if comparison > 0 else _('reduction')
        return self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.deal_id.partner_id.id,
            'company_id': self.deal_id.company_id.id,
            'invoice_date': fields.Date.context_today(self),
            'deal_id': self.deal_id.id,
            'petro_price_adjustment': 'customer_sell',
            'petro_original_move_id': original.id,
            'petro_adjustment_scope': 'sold',
            'petro_old_price': effective_price,
            'petro_new_price': self.new_sell_price,
            'petro_adjustment_quantity': self.new_quantity,
            'invoice_origin': original.name,
            'ref': _('Customer price %(direction)s — %(deal)s',
                     direction=direction, deal=self.deal_id.name),
            'invoice_line_ids': [fields.Command.create({
                'product_id': self.product_id.id,
                'name': _(
                    'Customer price %(direction)s on %(product)s: '
                    '%(old)s → %(new)s (%(qty)s L). %(note)s',
                    direction=direction,
                    product=self.product_id.display_name,
                    old=effective_price,
                    new=self.new_sell_price,
                    qty=self.new_quantity,
                    note=self.note,
                ),
                'quantity': self.new_quantity,
                'price_unit': delta,
                'tax_ids': [fields.Command.set(taxes.ids)],
                'product_uom_id': self.product_id.uom_id.id,
            })],
        })

    def _action_open_draft_moves(self, moves):
        self.ensure_one()
        if len(moves) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Deal Revision Document'),
                'res_model': 'account.move',
                'res_id': moves.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Deal Revision Documents'),
            'res_model': 'account.move',
            'domain': [('id', 'in', moves.ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_confirm(self):
        self.ensure_one()
        deal = self.deal_id
        line = self.deal_line_id
        if deal.state != 'confirmed':
            raise UserError(_(
                'Only deals in Confirmed status can be revised with this action.'))
        if self.new_quantity <= 0:
            raise UserError(_('New litres must be greater than zero.'))

        effective_price = self._effective_sell_price(line)
        same_qty = self._qty_compare(self.new_quantity, line.quantity) == 0
        same_price = self._price_compare(self.new_sell_price, effective_price) == 0
        if same_qty and same_price:
            raise UserError(_('Enter a new quantity or sell price to revise.'))

        sale_line = self._find_sale_order_line()
        invoiced = self._ensure_invoice_revision_allowed(sale_line)
        old_quantity = line.quantity
        old_price = effective_price if invoiced else line.sell_price

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

        drafts = self.env['account.move']
        if invoiced:
            original = self._original_invoice()
            drafts |= self._create_quantity_adjustment_move(
                original, old_quantity, effective_price)
            drafts |= self._create_price_adjustment_move(original, effective_price)

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
        if drafts:
            return self._action_open_draft_moves(drafts)
        return {'type': 'ir.actions.act_window_close'}
