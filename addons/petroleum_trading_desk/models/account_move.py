import re

from odoo import api, fields, models, _

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
    petro_margin_total = fields.Monetary(
        string='Margin', compute='_compute_petro_margin_total', store=True,
        currency_field='currency_id')

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
