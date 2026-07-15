from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class PetroleumDailyPositionLine(models.Model):
    _name = 'petroleum.daily.position.line'
    _description = 'Daily Fuel Position'
    _order = 'date desc, product_id, supplier_id, buy_price'

    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today, index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('fuel_ok', '=', True)]")
    supplier_id = fields.Many2one(
        'res.partner', string='Supplier', required=True,
        domain="[('supplier_rank', '>', 0)]")
    depot_id = fields.Many2one('petroleum.depot', string='Depot')
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    qty_opening = fields.Float(
        string='Opening (Rolled)', digits='Product Unit of Measure', default=0.0,
        help='Unsold volume carried forward from the previous day.')
    qty_bought = fields.Float(
        string='Bought Today', digits='Product Unit of Measure', default=0.0,
        help='New bulk volume purchased this morning.')
    qty_total = fields.Float(
        string='Total Available', compute='_compute_quantities', store=True,
        digits='Product Unit of Measure')
    qty_sold = fields.Float(
        string='Allocated', compute='_compute_quantities', store=True,
        digits='Product Unit of Measure')
    qty_remaining = fields.Float(
        string='Remaining', compute='_compute_quantities', store=True,
        digits='Product Unit of Measure')

    buy_price = fields.Float(string='Buy Price', digits='Product Price')
    sell_price = fields.Float(string='Sell Price', digits='Product Price')
    margin = fields.Float(
        string='Margin', compute='_compute_margin', store=True, digits='Product Price')

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', copy=False)
    purchase_order_line_id = fields.Many2one(
        'purchase.order.line', string='PO Line', copy=False)
    rolled_from_line_id = fields.Many2one(
        'petroleum.daily.position.line', string='Rolled From', copy=False, readonly=True)
    rolled_forward_on = fields.Date(
        string='Rolled On', copy=False, readonly=True,
        help='Set when this line\'s unsold volume was carried to the next day.')

    allocation_ids = fields.One2many(
        'petroleum.daily.position.allocation', 'position_line_id', string='Allocations')
    price_history_ids = fields.One2many(
        'petroleum.daily.position.price.history', 'position_line_id', string='Price History')
    note = fields.Char(string='Note')

    def _price_precision(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        return currency.decimal_places if currency else 2

    def _same_buy_price(self, other_price):
        """Compare buy prices using currency rounding."""
        self.ensure_one()
        return float_compare(
            self.buy_price, other_price, precision_digits=self._price_precision()
        ) == 0

    @api.depends('qty_opening', 'qty_bought', 'allocation_ids.quantity', 'allocation_ids.state')
    def _compute_quantities(self):
        for line in self:
            line.qty_total = line.qty_opening + line.qty_bought
            sold = sum(line.allocation_ids.filtered(
                lambda a: a.state == 'active').mapped('quantity'))
            line.qty_sold = sold
            line.qty_remaining = line.qty_total - sold

    @api.depends('buy_price', 'sell_price')
    def _compute_margin(self):
        for line in self:
            line.margin = line.sell_price - line.buy_price

    @api.constrains('date', 'product_id', 'supplier_id', 'depot_id', 'company_id', 'buy_price')
    def _check_unique_line(self):
        """One line per date/product/supplier/depot/company/buy-price lot.

        Same supplier and product may be bought several times on the same day
        as long as each purchase has a distinct buy price.
        """
        for line in self:
            domain = [
                ('date', '=', line.date),
                ('product_id', '=', line.product_id.id),
                ('supplier_id', '=', line.supplier_id.id),
                ('depot_id', '=', line.depot_id.id),
                ('company_id', '=', line.company_id.id),
                ('id', '!=', line.id),
            ]
            for other in self.search(domain):
                if line._same_buy_price(other.buy_price):
                    raise ValidationError(_(
                        'A position line already exists for %(product)s / %(supplier)s '
                        'on %(date)s at buy price %(price)s. '
                        'Add another line only when the buy price is different.',
                        product=line.product_id.display_name,
                        supplier=line.supplier_id.display_name,
                        date=line.date,
                        price=line.buy_price,
                    ))

    @api.constrains('qty_opening', 'qty_bought')
    def _check_non_negative_qty(self):
        for line in self:
            if line.qty_opening < 0 or line.qty_bought < 0:
                raise ValidationError(_('Quantities cannot be negative.'))

    def _log_buy_price_change(self, old_price, new_price, reason='revision', note=False):
        self.ensure_one()
        if old_price == new_price:
            return
        self.env['petroleum.daily.position.price.history'].create({
            'position_line_id': self.id,
            'date': self.date,
            'old_buy_price': old_price,
            'new_buy_price': new_price,
            'reason': reason,
            'note': note or '',
        })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line, vals in zip(lines, vals_list):
            if vals.get('buy_price') and not vals.get('rolled_from_line_id'):
                line._log_buy_price_change(0.0, vals['buy_price'], reason='initial')
        return lines

    def write(self, vals):
        price_logs = []
        if 'buy_price' in vals:
            for line in self:
                price_logs.append((line, line.buy_price, vals['buy_price']))
        res = super().write(vals)
        reason = self.env.context.get('buy_price_log_reason', 'revision')
        note = self.env.context.get('buy_price_log_note', False)
        for line, old_price, new_price in price_logs:
            line._log_buy_price_change(old_price, new_price, reason=reason, note=note)
        return res

    @api.model
    def _line_domain(self, date, product, supplier, depot, company):
        return [
            ('date', '=', date),
            ('product_id', '=', product.id if hasattr(product, 'id') else product),
            ('supplier_id', '=', supplier.id if hasattr(supplier, 'id') else supplier),
            ('depot_id', '=', depot.id if depot else False),
            ('company_id', '=', company.id if hasattr(company, 'id') else company),
        ]

    @api.model
    def _pick_matching_line(self, candidates, buy_price=None, qty_needed=0.0):
        """Choose the best position lot among product/supplier/depot matches.

        Prefer an exact buy-price lot when a price is known; otherwise the
        first lot with enough remaining volume (FIFO by id).
        """
        if not candidates:
            return candidates.browse()
        if buy_price:
            priced = candidates.filtered(lambda l: l._same_buy_price(buy_price))
            if priced:
                with_stock = priced.filtered(lambda l: l.qty_remaining >= qty_needed)
                return (with_stock or priced)[:1]
        with_stock = candidates.filtered(lambda l: l.qty_remaining >= qty_needed)
        if with_stock:
            return with_stock.sorted('id')[:1]
        return candidates.sorted('id')[:1]

    @api.model
    def find_for_deal_line(self, deal_line):
        """Match a deal line to today's position lot (product, supplier, depot, price).

        If the deal line explicitly selects a position lot, that wins.
        """
        if deal_line.position_line_id:
            return deal_line.position_line_id
        deal = deal_line.deal_id
        candidates = self.candidates_for_deal_line(deal_line)
        return self._pick_matching_line(
            candidates, buy_price=deal_line.buy_price, qty_needed=deal_line.quantity)

    @api.model
    def candidates_for_deal_line(self, deal_line):
        """All same-day lots that could supply this deal line.

        Depot is soft-matched: if the deal has a depot, prefer that depot (and
        lots with no depot). If the deal has no depot, every depot matches so
        traders can still pick Buy Lots from KPRL / GAPCO, etc.
        """
        deal = deal_line.deal_id
        if not (deal and deal_line.product_id and deal_line.supplier_id and deal.date):
            return self.browse()
        domain = [
            ('date', '=', deal.date),
            ('product_id', '=', deal_line.product_id.id),
            ('supplier_id', '=', deal_line.supplier_id.id),
            ('company_id', '=', deal.company_id.id),
        ]
        if deal.depot_id:
            domain.append(('depot_id', 'in', [deal.depot_id.id, False]))
        return self.search(domain, order='buy_price, id')

    def _get_linked_purchase_order(self):
        """PO for this lot, walking rolled-from ancestors for opening stock.

        Carried-forward lines often have no PO of their own (stock was bought
        on an earlier day). Trips and deal confirm still need that original PO.
        """
        self.ensure_one()
        seen = self.env['petroleum.daily.position.line']
        line = self
        while line and line not in seen:
            seen |= line
            if line.purchase_order_id:
                return line.purchase_order_id
            line = line.rolled_from_line_id
        return self.env['purchase.order']

    def _po_origin(self):
        self.ensure_one()
        return 'DP/%s/%s' % (self.date, self.supplier_id.id)

    @api.model
    def _get_or_create_supplier_po(self, supplier, pos_date, company, depot=False):
        PurchaseOrder = self.env['purchase.order']
        domain = [
            ('partner_id', '=', supplier.id),
            ('is_daily_position_po', '=', True),
            ('daily_position_date', '=', pos_date),
            ('company_id', '=', company.id),
        ]
        po = PurchaseOrder.search(domain, limit=1)
        if po:
            return po
        return PurchaseOrder.create({
            'partner_id': supplier.id,
            'origin': 'DP/%s/%s' % (pos_date, supplier.display_name),
            'date_order': fields.Datetime.to_datetime(pos_date),
            'company_id': company.id,
            'depot_id': depot.id if depot else False,
            'is_daily_position_po': True,
            'daily_position_date': pos_date,
        })

    def _sync_purchase_order_line(self):
        """Create or update the bulk PO line for new buys on this position.

        Only ``qty_bought`` is synced — rolled opening stock was already
        purchased on a prior day and must not inflate today's PO.
        """
        self.ensure_one()
        if self.qty_bought <= 0:
            return
        if not self.buy_price:
            raise UserError(_(
                'Set a buy price on %(product)s before syncing purchase orders.',
                product=self.product_id.display_name,
            ))
        po = self._get_or_create_supplier_po(
            self.supplier_id, self.date, self.company_id, self.depot_id)
        po_line = self.purchase_order_line_id
        if po_line and po_line.order_id != po:
            po_line = False
        if not po_line:
            po_line = self.env['purchase.order.line'].search([
                ('order_id', '=', po.id),
                ('product_id', '=', self.product_id.id),
                ('petroleum_position_line_id', '=', self.id),
            ], limit=1)
        vals = {
            'product_id': self.product_id.id,
            'name': '%s @ %s' % (self.product_id.display_name, self.buy_price),
            'product_qty': self.qty_bought,
            'product_uom_id': self.product_id.uom_id.id,
            'price_unit': self.buy_price,
            'date_planned': fields.Datetime.to_datetime(self.date),
            'petroleum_position_line_id': self.id,
        }
        if po_line:
            po_line.write(vals)
        else:
            po_line = self.env['purchase.order.line'].create({
                'order_id': po.id,
                **vals,
            })
        self.write({
            'purchase_order_id': po.id,
            'purchase_order_line_id': po_line.id,
        })
        self._complete_daily_position_po(po)

    @api.model
    def _complete_daily_position_po(self, po):
        """Confirm the bulk PO, validate receipt, and post the vendor bill."""
        if po.state in ('draft', 'sent'):
            po.button_confirm()
        # Idempotent for already-confirmed POs that missed receipt/bill.
        po._auto_validate_receipt()
        po._auto_create_vendor_bill()
        bills = po.invoice_ids.filtered(
            lambda m: m.state == 'draft' and m.move_type == 'in_invoice')
        if bills:
            invoice_date = po.daily_position_date or fields.Date.context_today(self)
            bill_vals = {
                'invoice_date': invoice_date,
                # Bill Reference / Source Document → PO number (e.g. P00099).
                'ref': po.name,
                'invoice_origin': po.name,
            }
            if 'purchase_id' in bills._fields:
                bill_vals['purchase_id'] = po.id
            bills.write(bill_vals)
            bills.action_post()

    def action_sync_purchase_orders(self):
        """Create or update bulk POs for selected lines, or all of today from the list.

        Each sync confirms the PO, validates the goods receipt, and posts the
        supplier bill so the morning position is fully booked in one step.
        """
        if self:
            lines = self.filtered(lambda line: line.qty_bought > 0)
        else:
            today = fields.Date.context_today(self)
            lines = self.search([
                ('date', '=', today),
                ('qty_bought', '>', 0),
            ])
        if not lines:
            raise UserError(_(
                'Add position lines with Bought Today volume before syncing '
                'purchase orders. Rolled opening stock is not re-purchased.'
            ))
        errors = []
        for line in lines:
            try:
                line._sync_purchase_order_line()
            except UserError as exc:
                errors.append('%s — %s' % (line.display_name, exc.args[0]))
        if errors:
            raise UserError('\n'.join(errors))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Purchase orders synced'),
                'message': _(
                    '%d position line(s) linked — purchase confirmed, goods '
                    'received, and supplier bill posted.'
                ) % len(lines),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    @api.model
    def _find_today_lot(self, today, product, supplier, depot, company, buy_price):
        """Find today's position lot matching product/supplier/depot/buy price."""
        candidates = self.search(
            self._line_domain(today, product, supplier, depot, company), order='id')
        return candidates.filtered(lambda l: l._same_buy_price(buy_price))[:1]

    def action_carry_forward(self):
        """Roll unsold volume from any prior day into today and open the board.

        Looks beyond calendar yesterday so weekends / skipped trading days
        still carry remaining stock forward. Each buy-price lot rolls into
        its own opening line for today.
        """
        today = fields.Date.context_today(self)
        prev_lines = self.search([
            ('date', '<', today),
            ('qty_remaining', '>', 0),
            ('rolled_forward_on', '=', False),
        ], order='date, id')
        rolled_count = 0
        rolled_qty = 0.0
        for prev in prev_lines:
            existing = self._find_today_lot(
                today, prev.product_id, prev.supplier_id, prev.depot_id,
                prev.company_id, prev.buy_price)
            roll_qty = prev.qty_remaining
            if existing:
                existing.write({'qty_opening': existing.qty_opening + roll_qty})
                # Keep a PO link for sales from rolled opening when possible.
                if not existing.purchase_order_id:
                    source_po = prev._get_linked_purchase_order()
                    if source_po:
                        existing.write({
                            'purchase_order_id': source_po.id,
                            'purchase_order_line_id': (
                                prev.purchase_order_line_id.id
                                if prev.purchase_order_line_id else False),
                        })
            else:
                source_po = prev._get_linked_purchase_order()
                new_line = self.create({
                    'date': today,
                    'product_id': prev.product_id.id,
                    'supplier_id': prev.supplier_id.id,
                    'depot_id': prev.depot_id.id,
                    'company_id': prev.company_id.id,
                    'qty_opening': roll_qty,
                    'buy_price': prev.buy_price,
                    'sell_price': prev.sell_price,
                    'rolled_from_line_id': prev.id,
                    'purchase_order_id': source_po.id if source_po else False,
                    'purchase_order_line_id': (
                        prev.purchase_order_line_id.id
                        if prev.purchase_order_line_id else False),
                })
                new_line._log_buy_price_change(
                    0.0, prev.buy_price, reason='roll_forward',
                    note=_('Rolled %(qty)s L from %(date)s',
                           qty=roll_qty, date=prev.date))
            prev.write({'rolled_forward_on': today})
            rolled_count += 1
            rolled_qty += roll_qty

        self.env['petroleum.daily.price']._carry_forward_prices(today)
        if rolled_count:
            title = _('Stock carried forward')
            message = _(
                'Rolled %(count)d line(s) / %(qty).2f L into today.',
                count=rolled_count, qty=rolled_qty)
            ntype = 'success'
        else:
            title = _('Nothing to carry forward')
            message = _(
                'No unrolled remaining stock found before today. '
                'Check previous days for remaining volume that is still '
                'allocated to deals (cancel those deals first), or lines '
                'already marked as rolled.')
            ntype = 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': ntype,
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    @api.depends('date', 'product_id', 'supplier_id', 'depot_id', 'buy_price', 'qty_remaining')
    def _compute_display_name(self):
        lot_label = self.env.context.get('deal_position_lot_name')
        for line in self:
            if lot_label:
                line.display_name = _('%(price)s — %(qty)s L left',
                                      price=line.buy_price,
                                      qty=line.qty_remaining)
                continue
            depot = line.depot_id.code or line.depot_id.name or ''
            parts = [
                fields.Date.to_string(line.date),
                line.product_id.display_name,
                line.supplier_id.display_name,
            ]
            if depot:
                parts.append(depot)
            if line.buy_price:
                parts.append('@ %s' % line.buy_price)
            line.display_name = ' / '.join(parts)

    def action_open_revise_buy_price(self):
        """Open the supplier / lot price revision wizard for one position line."""
        self.ensure_one()
        if self.qty_remaining <= 0:
            raise UserError(_(
                'Nothing left to revise on %(line)s — remaining stock is zero.',
                line=self.display_name,
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Revise Buy Price'),
            'res_model': 'petroleum.daily.position.revise.price',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_position_line_id': self.id,
                'default_new_buy_price': self.buy_price,
            },
        }

    def _find_merge_target(self, new_buy_price):
        """Another same-day lot that already owns ``new_buy_price``."""
        self.ensure_one()
        candidates = self.search([
            ('date', '=', self.date),
            ('product_id', '=', self.product_id.id),
            ('supplier_id', '=', self.supplier_id.id),
            ('depot_id', '=', self.depot_id.id),
            ('company_id', '=', self.company_id.id),
            ('id', '!=', self.id),
        ])
        return candidates.filtered(lambda l: l._same_buy_price(new_buy_price))[:1]

    def _transfer_remaining_to(self, target):
        """Move remaining litres onto ``target`` as opening stock; keep sold history here."""
        self.ensure_one()
        target.ensure_one()
        remaining = self.qty_remaining
        if remaining <= 0:
            return 0.0
        reduce_opening = min(self.qty_opening, remaining)
        reduce_bought = remaining - reduce_opening
        self.write({
            'qty_opening': self.qty_opening - reduce_opening,
            'qty_bought': self.qty_bought - reduce_bought,
        })
        target.write({'qty_opening': target.qty_opening + remaining})
        # Re-point open (not yet confirmed) deal lines to the surviving lot.
        draft_lines = self.env['petroleum.deal.line'].search([
            ('position_line_id', '=', self.id),
            ('deal_id.state', 'in', ('draft', 'proforma')),
        ])
        if draft_lines:
            draft_lines.write({
                'position_line_id': target.id,
                'buy_price': target.buy_price,
            })
        return remaining

    def action_revise_buy_price(
            self, new_buy_price, note='', merge_into_matching=True,
            create_credit_note=True):
        """Revise remaining stock cost after a supplier price reduction.

        - Logs price history.
        - If a same-day lot already exists at ``new_buy_price``, merges remaining
          litres into it (sold allocations stay on this line for audit).
        - Otherwise updates this line's buy price.
        - Optionally creates a draft vendor credit note for the price drop on
          remaining litres.
        """
        self.ensure_one()
        precision = self._price_precision()
        new_price = float(new_buy_price)
        if float_compare(new_price, 0.0, precision_digits=precision) < 0:
            raise UserError(_('New buy price cannot be negative.'))
        if self._same_buy_price(new_price):
            raise UserError(_('New buy price is the same as the current buy price.'))
        remaining = self.qty_remaining
        if remaining <= 0:
            raise UserError(_('No remaining volume to revise on this lot.'))

        old_price = self.buy_price
        note = (note or '').strip() or _(
            'Supplier price reduction on remaining stock.')
        merge_target = self._find_merge_target(new_price)
        credit_note = self.env['account.move']
        transferred = 0.0

        if merge_into_matching and merge_target:
            self._log_buy_price_change(
                old_price, new_price, reason='supplier_reduction',
                note=_('%(note)s — merged %(qty)s L into lot @ %(price)s.',
                       note=note, qty=remaining, price=new_price))
            transferred = self._transfer_remaining_to(merge_target)
            surviving = merge_target
        elif merge_target and not merge_into_matching:
            raise UserError(_(
                'A position lot already exists at buy price %(price)s. '
                'Enable “Merge into matching lot” or pick a different price.',
                price=new_price,
            ))
        else:
            self.with_context(
                buy_price_log_reason='supplier_reduction',
                buy_price_log_note=note,
            ).write({'buy_price': new_price})
            # Refresh draft deals still pointing at this lot.
            draft_lines = self.env['petroleum.deal.line'].search([
                ('position_line_id', '=', self.id),
                ('deal_id.state', 'in', ('draft', 'proforma')),
            ])
            if draft_lines:
                draft_lines.write({'buy_price': new_price})
            surviving = self
            transferred = remaining

        if create_credit_note and float_compare(
                old_price, new_price, precision_digits=precision) > 0:
            credit_note = self._create_supplier_price_credit_note(
                old_price, new_price, transferred or remaining, note)

        return {
            'surviving_line': surviving,
            'credit_note': credit_note,
            'transferred_qty': transferred or remaining,
            'merged': bool(merge_into_matching and merge_target),
            'old_price': old_price,
            'new_price': new_price,
        }

    def _create_supplier_price_credit_note(self, old_price, new_price, quantity, note):
        """Draft vendor credit note for (old − new) × remaining litres."""
        self.ensure_one()
        unit_credit = old_price - new_price
        if unit_credit <= 0 or quantity <= 0:
            return self.env['account.move']

        product = self.product_id
        po = self.purchase_order_id
        # Prefer tax from the linked PO line when available.
        taxes = self.env['account.tax']
        if self.purchase_order_line_id and self.purchase_order_line_id.tax_ids:
            taxes = self.purchase_order_line_id.tax_ids
        elif product.supplier_taxes_id:
            taxes = product.supplier_taxes_id.filtered(
                lambda t: t.company_id == self.company_id)

        line_name = _(
            'Supplier price reduction on %(product)s: %(old)s → %(new)s '
            '(%(qty)s L). %(note)s',
            product=product.display_name,
            old=old_price,
            new=new_price,
            qty=quantity,
            note=note,
        )
        move_vals = {
            'move_type': 'in_refund',
            'partner_id': self.supplier_id.id,
            'company_id': self.company_id.id,
            'invoice_date': fields.Date.context_today(self),
            'ref': _('Price reduction %(product)s @ %(old)s→%(new)s',
                     product=product.display_name, old=old_price, new=new_price),
            'invoice_origin': po.name if po else self.display_name,
            'invoice_line_ids': [fields.Command.create({
                'product_id': product.id,
                'name': line_name,
                'quantity': quantity,
                'price_unit': unit_credit,
                'tax_ids': [fields.Command.set(taxes.ids)],
                'product_uom_id': product.uom_id.id,
            })],
        }
        if 'purchase_id' in self.env['account.move']._fields and po:
            move_vals['purchase_id'] = po.id
        return self.env['account.move'].create(move_vals)

    def action_create_supplier_bills(self):
        """Post vendor bills for today's synced bulk purchase orders."""
        today = fields.Date.context_today(self)
        pos = self.env['purchase.order'].search([
            ('is_daily_position_po', '=', True),
            ('daily_position_date', '=', today),
            ('invoice_status', '=', 'to invoice'),
        ])
        if not pos:
            raise UserError(_('No bulk purchase orders ready to bill for today.'))
        for po in pos:
            po.action_create_invoice()
            bills = po.invoice_ids.filtered(
                lambda m: m.state == 'draft' and m.move_type == 'in_invoice')
            if bills:
                bill_vals = {
                    'invoice_date': today,
                    'ref': po.name,
                    'invoice_origin': po.name,
                }
                if 'purchase_id' in bills._fields:
                    bill_vals['purchase_id'] = po.id
                bills.write(bill_vals)
        bills = pos.invoice_ids.filtered(lambda m: m.state == 'draft')
        if bills:
            bills.action_post()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supplier bills posted'),
                'message': _('%d vendor bill(s) created for today\'s bulk buys.') % len(bills),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _action_open_today(self):
        today = fields.Date.context_today(self)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Daily Position'),
            'res_model': 'petroleum.daily.position.line',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('date', '=', today)],
            'context': {'default_date': today},
            'target': 'current',
        }


class PetroleumDailyPositionAllocation(models.Model):
    _name = 'petroleum.daily.position.allocation'
    _description = 'Daily Position Allocation'
    _order = 'id desc'

    position_line_id = fields.Many2one(
        'petroleum.daily.position.line', required=True, ondelete='cascade', index=True)
    deal_id = fields.Many2one(
        'petroleum.deal', required=True, ondelete='cascade', index=True)
    deal_line_id = fields.Many2one(
        'petroleum.deal.line', required=True, ondelete='cascade')
    quantity = fields.Float(required=True, digits='Product Unit of Measure')
    buy_price = fields.Float(digits='Product Price')
    state = fields.Selection([
        ('active', 'Active'),
        ('released', 'Released'),
    ], default='active', required=True, index=True)

    product_id = fields.Many2one(related='deal_line_id.product_id', store=True)
    supplier_id = fields.Many2one(related='position_line_id.supplier_id', store=True)
    date = fields.Date(related='position_line_id.date', store=True)


class PetroleumDailyPositionPriceHistory(models.Model):
    _name = 'petroleum.daily.position.price.history'
    _description = 'Daily Position Buy Price History'
    _order = 'create_date desc, id desc'

    position_line_id = fields.Many2one(
        'petroleum.daily.position.line', required=True, ondelete='cascade', index=True)
    date = fields.Date(required=True)
    old_buy_price = fields.Float(digits='Product Price')
    new_buy_price = fields.Float(string='Buy Price', digits='Product Price', required=True)
    reason = fields.Selection([
        ('initial', 'Initial entry'),
        ('roll_forward', 'Rolled from previous day'),
        ('revision', 'Manual revision'),
        ('supplier_reduction', 'Supplier price reduction'),
    ], required=True, default='revision')
    note = fields.Text()
    user_id = fields.Many2one(
        'res.users', string='Changed By', default=lambda self: self.env.uid, readonly=True)
