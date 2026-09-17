import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

_SKIP_INVOICE_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


def _strip_html(text):
    """Strip HTML tags and collapse whitespace."""
    if not text:
        return ''
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', text)).strip()


class AccountMove(models.Model):
    _inherit = 'account.move'

    deal_id = fields.Many2one(
        'petroleum.deal', string='Trading Deal', index=True, copy=False, ondelete='set null',
        help='Links this imported ledger invoice or bill to the matching Trading Desk deal.')
    petro_price_adjustment = fields.Selection([
        ('customer_sell', 'Customer Sell Price'),
        ('supplier_buy', 'Supplier Buy Price'),
    ], string='Petroleum Price Adjustment', copy=False, index=True,
        help='Identifies price-only documents so they affect margin without '
             'double-counting litres.')
    petro_original_move_id = fields.Many2one(
        'account.move', string='Original Petroleum Document', copy=False,
        ondelete='set null', index=True)
    petro_adjustment_scope = fields.Selection([
        ('remaining', 'Remaining Stock'),
        ('sold', 'Sold Volume'),
    ], string='Petroleum Adjustment Scope', copy=False)
    petro_old_price = fields.Float(
        string='Previous Petroleum Price', digits='Product Price', copy=False)
    petro_new_price = fields.Float(
        string='New Petroleum Price', digits='Product Price', copy=False)
    petro_adjustment_quantity = fields.Float(
        string='Adjusted Litres', digits='Product Unit of Measure', copy=False)
    petro_margin_total = fields.Monetary(
        string='Margin', compute='_compute_petro_margin_total', store=True,
        currency_field='currency_id')
    petro_qty_propagated = fields.Boolean(
        string='Litres Propagated', copy=False,
        help='Set when posting this manual refund / debit note updated the '
             'daily position lot or deal quantities. Resetting to draft '
             'restores them.')
    petroleum_expense_debtor_warning = fields.Char(
        compute='_compute_petroleum_expense_debtor_warning')

    @api.depends(
        'move_type', 'state',
        'line_ids.account_id', 'line_ids.account_id.account_type',
        'line_ids.partner_id', 'line_ids.display_type',
    )
    def _compute_petroleum_expense_debtor_warning(self):
        for move in self:
            move.petroleum_expense_debtor_warning = False
            if move.move_type != 'entry' or move.state == 'posted':
                continue
            lines = move.line_ids.filtered(
                lambda l: l.display_type not in _SKIP_INVOICE_LINE_DISPLAY)
            expense = lines.filtered(
                lambda l: l.account_id.account_type in (
                    'expense', 'expense_direct_cost'))
            receivable = lines.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable')
            if not expense or not receivable:
                continue
            if not receivable.partner_id:
                move.petroleum_expense_debtor_warning = _(
                    'Expense ↔ Debtor: set the Customer on the receivable '
                    '(debtor) line, or use Trading Desk → Accounting → '
                    'Expense ↔ Customer. Without a partner this will not hit '
                    'the customer statement.'
                )

    @api.depends(
        'invoice_line_ids.petro_margin',
        'invoice_line_ids.display_type',
        'invoice_line_ids.product_id',
        'invoice_line_ids.quantity',
        'invoice_line_ids.price_unit',
    )
    def _compute_petro_margin_total(self):
        for move in self:
            lines = move.invoice_line_ids.filtered(
                lambda l: l.display_type not in _SKIP_INVOICE_LINE_DISPLAY
                and l.product_id)
            move.petro_margin_total = sum(lines.mapped('petro_margin'))

    def write(self, vals):
        res = super().write(vals)
        if 'deal_id' in vals:
            self.filtered(
                lambda m: m.move_type in ('out_invoice', 'out_refund')
            )._compute_petro_margin_total()
            self.mapped('invoice_line_ids')._compute_petro_margin()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Keep reversals attached to the same deal for margin reporting."""
        for vals in vals_list:
            reversed_id = vals.get('reversed_entry_id')
            if reversed_id and not vals.get('deal_id'):
                original = self.browse(reversed_id)
                if original.deal_id:
                    vals['deal_id'] = original.deal_id.id
                vals.setdefault('petro_original_move_id', original.id)
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Propagate manual refunds / debit notes to litres and deals
    # ------------------------------------------------------------------

    def action_post(self):
        res = super().action_post()
        self._petro_propagate_qty_documents(direction=1)
        return res

    def button_draft(self):
        propagated = self.filtered('petro_qty_propagated')
        res = super().button_draft()
        propagated._petro_propagate_qty_documents(direction=-1)
        return res

    def _petro_qty_propagation_candidate(self):
        """Manual quantity refund / debit note that must move litres.

        Documents the desk already accounted for are excluded: price-only
        CN/DN (``petro_price_adjustment``), quantity documents created by the
        revision wizards (``petro_adjustment_quantity``), daily-position bill
        sync documents (context flag), and ledger imports.
        """
        self.ensure_one()
        if self.move_type not in (
                'in_refund', 'in_invoice', 'out_refund', 'out_invoice'):
            return False
        if self.petro_price_adjustment or self.petro_adjustment_quantity:
            return False
        if self.env.context.get('petro_position_sync'):
            return False
        if 'petro_import_batch' in self._fields and self.petro_import_batch:
            return False
        if self.move_type in ('in_refund', 'out_refund'):
            return True
        # Debit notes and reversals of refunds add litres back.
        debit_origin = (
            'debit_origin_id' in self._fields and self.debit_origin_id)
        return bool(debit_origin) or (
            self.reversed_entry_id
            and self.reversed_entry_id.move_type in ('in_refund', 'out_refund'))

    def _petro_vendor_capture_candidate(self):
        """Hand-typed vendor bill whose fuel litres may be new board stock.

        Bills flowing from purchase orders (daily-position sync or deal POs)
        are excluded per line through ``purchase_line_id``; flagged
        adjustment/wizard documents, sync posts, and ledger imports are
        excluded entirely.
        """
        self.ensure_one()
        if self.move_type != 'in_invoice' or not self.partner_id:
            return False
        if self.petro_price_adjustment or self.petro_adjustment_quantity:
            return False
        if self.env.context.get('petro_position_sync'):
            return False
        if 'petro_import_batch' in self._fields and self.petro_import_batch:
            return False
        return bool(self._petro_capture_lines())

    def _petro_capture_lines(self):
        """Fuel lines a hand-typed vendor bill contributes to the board."""
        return self._petro_product_lines().filtered(
            lambda line: not line.purchase_line_id)

    def _petro_propagate_qty_documents(self, direction):
        """Apply (direction=1) or undo (direction=-1) litres of manual docs."""
        for move in self:
            if direction > 0:
                if move.petro_qty_propagated:
                    continue
                is_refund_doc = move._petro_qty_propagation_candidate()
                is_capture_doc = (
                    not is_refund_doc and move._petro_vendor_capture_candidate())
                if not (is_refund_doc or is_capture_doc):
                    continue
            else:
                if not move.petro_qty_propagated:
                    continue
                is_refund_doc = move._petro_qty_propagation_candidate()
                is_capture_doc = (
                    not is_refund_doc and move.move_type == 'in_invoice')
            move = move.sudo()
            # Set the marker before applying so any flush triggered while
            # updating records (e.g. chatter posts recomputing deal amounts)
            # already sees this document as a propagated quantity document.
            move.petro_qty_propagated = direction > 0
            if is_capture_doc:
                changed = move._petro_capture_vendor_bill(direction)
            elif move.move_type in ('in_refund', 'in_invoice'):
                changed = move._petro_apply_vendor_qty_document(direction)
            else:
                changed = move._petro_apply_customer_qty_document(direction)
            if direction > 0 and not changed:
                move.petro_qty_propagated = False

    def _petro_capture_vendor_bill(self, direction):
        """Feed litres of a hand-typed vendor bill onto the position board.

        Only litres the board does not already know are added: when a lot for
        the bill date / product / supplier / unit price already exists, the
        bill is treated as the paperwork for that lot and nothing moves.
        Lots created here remember their source bill so a reset-to-draft
        removes exactly those litres (guarded against sold volume).
        """
        self.ensure_one()
        Position = self.env['petroleum.daily.position.line']
        supplier = self.partner_id.commercial_partner_id
        bill_date = self.invoice_date or fields.Date.context_today(self)
        changed = False
        for line in self._petro_capture_lines():
            own_lots = Position.search([
                ('created_from_move_id', '=', self.id),
                ('product_id', '=', line.product_id.id),
            ])
            own = own_lots.filtered(
                lambda lot: lot._same_buy_price(line.price_unit))[:1]
            if direction < 0:
                if not own:
                    continue
                own._petro_apply_external_qty_delta(
                    -line.quantity,
                    _('Vendor bill %(doc)s reset to draft (%(qty)s L '
                      'removed).', doc=self.display_name, qty=line.quantity))
                changed = True
                continue
            if own:
                # Re-posting a bill whose litres were removed on draft.
                old_remaining = own.qty_remaining
                own.write({'qty_bought': own.qty_bought + line.quantity})
                own._log_quantity_change(
                    old_remaining, own.qty_remaining,
                    note=_('Vendor bill %(doc)s posted (%(qty)s L).',
                           doc=self.display_name, qty=line.quantity))
                changed = True
                continue
            existing = Position.search([
                ('date', '=', bill_date),
                ('product_id', '=', line.product_id.id),
                ('supplier_id', 'in', (self.partner_id | supplier).ids),
                ('company_id', '=', self.company_id.id),
            ]).filtered(lambda lot: lot._same_buy_price(line.price_unit))
            if existing:
                # The board already carries these litres; the bill is just
                # their paperwork. Adding again would double the stock.
                continue
            lot = Position.create({
                'date': bill_date,
                'product_id': line.product_id.id,
                'supplier_id': supplier.id,
                'company_id': self.company_id.id,
                'currency_id': self.currency_id.id or False,
                'qty_bought': line.quantity,
                'buy_price': line.price_unit,
                'created_from_move_id': self.id,
                'note': _('Created from vendor bill %s', self.display_name),
            })
            lot._log_quantity_change(
                0.0, lot.qty_remaining,
                note=_('Vendor bill %(doc)s posted (%(qty)s L).',
                       doc=self.display_name, qty=line.quantity))
            changed = True
        return changed

    def _petro_product_lines(self):
        return self.invoice_line_ids.filtered(
            lambda line: line.display_type not in _SKIP_INVOICE_LINE_DISPLAY
            and line.product_id and line.product_id.fuel_ok
            and line.quantity)

    def _petro_line_sign(self):
        """Litres direction of this document: refunds remove, others add."""
        return -1.0 if self.move_type in ('in_refund', 'out_refund') else 1.0

    def _petro_trace_position_lot(self, line):
        """Best-effort match of a vendor document line to a position lot."""
        self.ensure_one()
        po_line = line.purchase_line_id
        if po_line and po_line.petroleum_position_line_id:
            return po_line.petroleum_position_line_id
        original = self.reversed_entry_id or self.petro_original_move_id
        if not original and 'debit_origin_id' in self._fields:
            original = self.debit_origin_id
        if original:
            for original_line in original.invoice_line_ids.filtered(
                    lambda ol: ol.product_id == line.product_id
                    and ol.purchase_line_id.petroleum_position_line_id):
                return original_line.purchase_line_id.petroleum_position_line_id
        po = self.env['purchase.order']._petro_po_from_origin(
            self.invoice_origin or self.ref)
        if po:
            po_line = po._petro_matching_order_line(
                product=line.product_id, old_price=line.price_unit)
            if po_line and po_line.petroleum_position_line_id:
                return po_line.petroleum_position_line_id
        return self.env['petroleum.daily.position.line']

    def _petro_apply_vendor_qty_document(self, direction):
        """Move litres of a manual vendor CN/DN on the traced position lots."""
        self.ensure_one()
        sign = self._petro_line_sign()
        changed = False
        for line in self._petro_product_lines():
            lot = self._petro_trace_position_lot(line)
            if not lot:
                continue
            delta = sign * direction * line.quantity
            if direction > 0:
                note = _('Vendor document %(doc)s posted (%(qty)s L).',
                         doc=self.display_name, qty=line.quantity)
            else:
                note = _('Vendor document %(doc)s reset to draft (%(qty)s L '
                         'restored).', doc=self.display_name, qty=line.quantity)
            lot._petro_apply_external_qty_delta(delta, note)
            changed = True
        return changed

    def _petro_shift_deal_allocation(self, deal_line, delta):
        """Adjust the deal line's active position allocations by ``delta``."""
        rounding = (
            deal_line.product_id.uom_id.rounding
            if deal_line.product_id.uom_id else 0.01)
        allocations = deal_line.deal_id.position_allocation_ids.filtered(
            lambda alloc: alloc.deal_line_id == deal_line
            and alloc.state == 'active').sorted('id')
        if delta > 0:
            pos_line = (
                allocations[:1].position_line_id
                or deal_line.position_line_id
                or self.env['petroleum.daily.position.line'].find_for_deal_line(
                    deal_line))
            if not pos_line or float_compare(
                    pos_line.qty_remaining, delta,
                    precision_rounding=rounding) < 0:
                raise UserError(_(
                    'Cannot post %(doc)s: no position lot has %(qty)s L '
                    'remaining for %(product)s. Use the deal revision wizard '
                    'instead.',
                    doc=self.display_name, qty=delta,
                    product=deal_line.product_id.display_name))
            if allocations:
                allocations[0].write(
                    {'quantity': allocations[0].quantity + delta})
            else:
                self.env['petroleum.daily.position.allocation'].create({
                    'position_line_id': pos_line.id,
                    'deal_id': deal_line.deal_id.id,
                    'deal_line_id': deal_line.id,
                    'quantity': delta,
                    'buy_price': deal_line.buy_price or pos_line.buy_price,
                })
            return
        remaining = -delta
        if float_compare(
                sum(allocations.mapped('quantity')), remaining,
                precision_rounding=rounding) < 0:
            raise UserError(_(
                'Cannot post %(doc)s: the active position allocation for '
                '%(product)s is smaller than %(qty)s L. Use the deal revision '
                'wizard instead.',
                doc=self.display_name, qty=remaining,
                product=deal_line.product_id.display_name))
        for allocation in allocations.sorted('id', reverse=True):
            if float_compare(
                    remaining, 0.0, precision_rounding=rounding) <= 0:
                break
            if float_compare(
                    remaining, allocation.quantity,
                    precision_rounding=rounding) >= 0:
                remaining -= allocation.quantity
                allocation.write({'state': 'released'})
            else:
                allocation.write(
                    {'quantity': allocation.quantity - remaining})
                remaining = 0.0

    def _petro_apply_customer_qty_document(self, direction):
        """Move litres of a manual customer CN/DN on the linked deal."""
        self.ensure_one()
        deal = self.deal_id
        if not deal or deal.state not in ('confirmed', 'loaded', 'done'):
            return False
        sign = self._petro_line_sign()
        changed = False
        for line in self._petro_product_lines():
            rounding = (
                line.product_id.uom_id.rounding
                if line.product_id.uom_id else 0.01)
            delta = sign * direction * line.quantity
            deal_lines = deal.line_ids.filtered(
                lambda dl: dl.product_id == line.product_id)
            if len(deal_lines) != 1:
                raise UserError(_(
                    'Cannot post %(doc)s: %(product)s does not match exactly '
                    'one line on deal %(deal)s. Use the deal revision wizard '
                    'instead.',
                    doc=self.display_name,
                    product=line.product_id.display_name,
                    deal=deal.name))
            deal_line = deal_lines
            new_qty = deal_line.quantity + delta
            if float_compare(
                    new_qty, 0.0, precision_rounding=rounding) <= 0:
                raise UserError(_(
                    'Cannot post %(doc)s: it would leave %(product)s on deal '
                    '%(deal)s at %(qty)s L. Use the deal revision wizard (or '
                    'cancel the deal) instead.',
                    doc=self.display_name,
                    product=line.product_id.display_name,
                    deal=deal.name, qty=new_qty))
            sale_lines = self.env['sale.order.line']
            if deal.sale_order_id:
                sale_lines = deal.sale_order_id.order_line.filtered(
                    lambda so_line: so_line.product_id == line.product_id
                    and not so_line.display_type)
                if len(sale_lines) > 1:
                    raise UserError(_(
                        'Cannot post %(doc)s: %(product)s appears on several '
                        'sale order lines of deal %(deal)s. Use the deal '
                        'revision wizard instead.',
                        doc=self.display_name,
                        product=line.product_id.display_name,
                        deal=deal.name))
            self._petro_shift_deal_allocation(deal_line, delta)
            deal_line.write({'quantity': new_qty})
            if sale_lines:
                sale_lines.write({
                    'product_uom_qty': sale_lines.product_uom_qty + delta})
            changed = True
        if changed:
            if direction > 0:
                body = _(
                    'Customer document %(doc)s posted — deal litres updated '
                    'accordingly.', doc=self.display_name)
            else:
                body = _(
                    'Customer document %(doc)s reset to draft — deal litres '
                    'restored.', doc=self.display_name)
            deal.message_post(body=body)
        return changed

    # ------------------------------------------------------------------
    # Backfill buy prices on imported ledger invoices
    # ------------------------------------------------------------------

    @api.model
    def action_backfill_import_buy_prices(self, date_from=None, date_to=None):
        """Set petro_buy_price on imported customer invoice lines by matching
        the corresponding vendor bill for the same truck plate, date and product.

        Ledger-imported invoices have the truck plate stored in ``narration``
        (as HTML, e.g. ``<p>KDU 024V</p>``).  The matching vendor bill has
        the same plate in its ``ref`` field.  We join on
        (invoice_date, truck_plate, product_id) to find the buy price.

        Matching strategy (in priority order):
        1. Exact truck + exact date
        2. Exact truck + ±1 day (common when loading day differs from billing day)
        3. Split-plate match: ``"KBK 733U/KCC 166U"`` → try each plate separately

        Call without arguments to backfill the entire import history, or
        pass ``date_from`` / ``date_to`` to limit the window.
        """
        from datetime import timedelta

        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('petro_import_batch', '!=', False),
        ]
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        if date_to:
            domain.append(('invoice_date', '<=', date_to))

        invoices = self.search(domain)
        if not invoices:
            return {'matched': 0, 'updated': 0}

        # ── Build buy-price lookup from posted vendor bills ────────────────
        # Key: (invoice_date, truck_plate_upper, product_id) → (bill_id, price_unit)
        # We load bills for a ±1 day window around the invoice dates.
        inv_dates = {m.invoice_date for m in invoices}
        bill_dates = set()
        for d in inv_dates:
            bill_dates.update([d - timedelta(days=1), d, d + timedelta(days=1)])

        buy_map = {}
        bills = self.search([
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
            ('petro_import_batch', '!=', False),
            ('invoice_date', 'in', list(bill_dates)),
        ])
        for bill in bills:
            truck_raw = _strip_html(bill.narration) or (bill.ref or '').strip()
            if not truck_raw:
                continue
            # Store under each individual plate so split lookups work both ways
            plates = [p.strip().upper() for p in truck_raw.replace('/', ',').split(',') if p.strip()]
            for plate in plates:
                for line in bill.invoice_line_ids:
                    if line.display_type in _SKIP_INVOICE_LINE_DISPLAY or not line.product_id:
                        continue
                    key = (bill.invoice_date, plate, line.product_id.id)
                    if key not in buy_map or bill.id > buy_map[key][0]:
                        buy_map[key] = (bill.id, line.price_unit)

        # ── Update customer invoice lines ──────────────────────────────────
        updated_lines = self.env['account.move.line']
        for inv in invoices:
            truck_raw = _strip_html(inv.narration)
            if not truck_raw:
                continue
            # Try each plate fragment (handles "PLATE1/PLATE2" combined references)
            cust_plates = [p.strip().upper() for p in truck_raw.replace('/', ',').split(',') if p.strip()]
            for line in inv.invoice_line_ids:
                if line.display_type in _SKIP_INVOICE_LINE_DISPLAY or not line.product_id:
                    continue
                if line.petro_buy_price:
                    continue
                entry = None
                # Priority 1: exact date
                for plate in cust_plates:
                    entry = buy_map.get((inv.invoice_date, plate, line.product_id.id))
                    if entry:
                        break
                # Priority 2: ±1 day
                if not entry:
                    for delta in (1, -1):
                        adj_date = inv.invoice_date + timedelta(days=delta)
                        for plate in cust_plates:
                            entry = buy_map.get((adj_date, plate, line.product_id.id))
                            if entry:
                                break
                        if entry:
                            break
                if entry:
                    line.petro_buy_price = entry[1]
                    updated_lines |= line

        # Trigger stored-field recompute
        if updated_lines:
            updated_lines._compute_petro_margin()

        return {
            'matched': len(updated_lines),
            'updated': len(invoices),
        }

    def action_backfill_import_buy_prices_ui(self):
        """Server-action entry point — runs backfill and shows a notification."""
        result = self.env['account.move'].action_backfill_import_buy_prices()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Buy Prices Backfilled'),
                'message': _(
                    'Updated buy price on %(n)d invoice line(s) across %(inv)d imported '
                    'customer invoice(s).  Margins have been recomputed.',
                    n=result['matched'],
                    inv=result['updated'],
                ),
                'type': 'success',
                'sticky': True,
            },
        }
