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
        for line, old_price, new_price in price_logs:
            line._log_buy_price_change(old_price, new_price)
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
        """Match a deal line to today's position lot (product, supplier, depot, price)."""
        deal = deal_line.deal_id
        domain = self._line_domain(
            deal.date, deal_line.product_id, deal_line.supplier_id,
            deal.depot_id, deal.company_id)
        candidates = self.search(domain, order='id')
        if not candidates and deal.depot_id:
            domain = self._line_domain(
                deal.date, deal_line.product_id, deal_line.supplier_id,
                False, deal.company_id)
            candidates = self.search(domain, order='id')
        return self._pick_matching_line(
            candidates, buy_price=deal_line.buy_price, qty_needed=deal_line.quantity)

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
            bills.write({'invoice_date': invoice_date})
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
            },
        }

    @api.model
    def _find_today_lot(self, today, product, supplier, depot, company, buy_price):
        """Find today's position lot matching product/supplier/depot/buy price."""
        candidates = self.search(
            self._line_domain(today, product, supplier, depot, company), order='id')
        return candidates.filtered(lambda l: l._same_buy_price(buy_price))[:1]

    @api.model
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
            else:
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
                })
                new_line._log_buy_price_change(
                    0.0, prev.buy_price, reason='roll_forward',
                    note=_('Rolled %(qty)s L from %(date)s',
                           qty=roll_qty, date=prev.date))
            prev.write({'rolled_forward_on': today})
            rolled_count += 1
            rolled_qty += roll_qty

        self.env['petroleum.daily.price']._carry_forward_prices(today)
        action = self._action_open_today()
        if rolled_count:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Stock carried forward'),
                    'message': _(
                        'Rolled %(count)d line(s) / %(qty).2f L into today.',
                        count=rolled_count, qty=rolled_qty),
                    'type': 'success',
                    'sticky': False,
                    'next': action,
                },
            }
        else:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Nothing to carry forward'),
                    'message': _(
                        'No unrolled remaining stock found before today. '
                        'Check previous days for remaining volume that is still '
                        'allocated to deals (cancel those deals first), or lines '
                        'already marked as rolled.'),
                    'type': 'warning',
                    'sticky': False,
                    'next': self._action_open_today(),
                },
            }
        return action

    @api.depends('date', 'product_id', 'supplier_id', 'depot_id', 'buy_price')
    def _compute_display_name(self):
        for line in self:
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
        bills = pos.invoice_ids.filtered(lambda m: m.state == 'draft')
        if bills:
            bills.write({'invoice_date': today})
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
    ], required=True, default='revision')
    note = fields.Text()
    user_id = fields.Many2one(
        'res.users', string='Changed By', default=lambda self: self.env.uid, readonly=True)
