import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Partners used for unsold / placeholder loads — never link ledger documents.
_SKIP_PARTNER_NAMES = frozenset({'NOT SOLD', 'NOTSOLD', 'UNSOLD'})


class PetroleumDeal(models.Model):
    _inherit = 'petroleum.deal'

    ledger_move_ids = fields.One2many(
        'account.move', 'deal_id', string='Linked Ledger Documents', copy=False)
    ledger_link_state = fields.Selection(
        [('none', 'Not Linked'), ('partial', 'Partially Linked'), ('full', 'Fully Linked')],
        string='Ledger Link', compute='_compute_ledger_link_state', store=True)

    # ------------------------------------------------------------------
    @api.depends(
        'ledger_move_ids', 'ledger_move_ids.move_type',
        'line_ids.supplier_id', 'line_ids.cost_subtotal', 'amount_sell', 'amount_buy',
        'partner_id', 'truck_id',
    )
    def _compute_ledger_link_state(self):
        for deal in self:
            deal.ledger_link_state = deal._ledger_link_state_value()

    @api.depends(
        'sale_order_id.invoice_ids', 'purchase_order_ids.invoice_ids',
        'ledger_move_ids', 'ledger_move_ids.move_type',
    )
    def _compute_links(self):
        for deal in self:
            so_invoices = deal.sale_order_id.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice')
            so_bills = deal.purchase_order_ids.invoice_ids.filtered(
                lambda m: m.move_type == 'in_invoice')
            ledger_invoices = deal.ledger_move_ids.filtered(
                lambda m: m.move_type == 'out_invoice')
            ledger_bills = deal.ledger_move_ids.filtered(
                lambda m: m.move_type == 'in_invoice')
            deal.invoice_ids = so_invoices | ledger_invoices
            deal.bill_ids = so_bills | ledger_bills
            deal.po_count = len(deal.purchase_order_ids)
            deal.invoice_count = len(deal.invoice_ids)
            deal.bill_count = len(deal.bill_ids)

    # ------------------------------------------------------------------
    # Matching helpers
    # ------------------------------------------------------------------
    def _ledger_skip_partner(self):
        self.ensure_one()
        return (self.partner_id.name or '').strip().upper() in _SKIP_PARTNER_NAMES

    def _ledger_plate(self):
        self.ensure_one()
        return re.sub(r'\s+', '', (self.truck_id.name or '').upper())

    def _ledger_partner_match_ids(self, partner, role='customer', use_aliases=True):
        """Strict Odoo partner tree + optional configured ledger aliases."""
        self.ensure_one()
        return self.env['petroleum.ledger.partner.alias'].ledger_partner_match_ids(
            self.company_id, partner, role=role, use_aliases=use_aliases)

    @staticmethod
    def _ledger_move_text(move):
        parts = [
            move.ref or '',
            move.narration or '',
            move.payment_reference or '',
            move.invoice_origin or '',
        ]
        return re.sub(r'\s+', '', ' '.join(parts).upper())

    def _ledger_move_has_plate(self, move, plate):
        if not plate:
            return True
        return plate in self._ledger_move_text(move)

    def _ledger_amount_tolerance(self, expected):
        """Allow small rounding drift between Excel and Odoo tax lines."""
        self.ensure_one()
        cur = self.company_id.currency_id
        return max(cur.rounding * 10, abs(expected) * 0.005, 1.0)

    def _ledger_amount_ok(self, move_amount, expected):
        return abs(move_amount - expected) <= self._ledger_amount_tolerance(expected)

    def _ledger_base_domain(self, move_type, only_imported):
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('move_type', '=', move_type),
            ('state', '=', 'posted'),
            ('deal_id', '=', False),
            ('invoice_date', '=', self.date),
        ]
        if only_imported:
            domain.append(('petro_import_batch', '!=', False))
        return domain

    def _ledger_pick_best(self, candidates, expected_amount):
        self.ensure_one()
        if not candidates:
            return self.env['account.move']
        if len(candidates) == 1:
            return candidates
        return candidates.sorted(
            key=lambda m: abs(m.amount_total_signed - expected_amount))[:1]

    def _ledger_supplier_amounts(self):
        self.ensure_one()
        totals = {}
        for line in self.line_ids:
            if not line.supplier_id or not line.cost_subtotal:
                continue
            sid = line.supplier_id.commercial_partner_id.id
            totals[sid] = totals.get(sid, 0.0) + line.cost_subtotal
        return totals

    def _ledger_filter_moves(self, moves, plate, expected_amount, require_truck):
        return moves.filtered(
            lambda m: (not require_truck or self._ledger_move_has_plate(m, plate))
            and self._ledger_amount_ok(abs(m.amount_total_signed), expected_amount))

    def _ledger_find_customer_invoice(
            self, only_imported=True, require_truck=True, use_aliases=True):
        self.ensure_one()
        if self._ledger_skip_partner():
            return self.env['account.move']
        plate = self._ledger_plate()
        if require_truck and not plate:
            return self.env['account.move']

        from datetime import timedelta

        Move = self.env['account.move']
        partner_ids = self._ledger_partner_match_ids(
            self.partner_id, role='customer', use_aliases=use_aliases)

        def _search_date(date):
            base = [
                ('company_id', '=', self.company_id.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('deal_id', '=', False),
                ('invoice_date', '=', date),
                ('partner_id', 'in', partner_ids),
            ]
            if only_imported:
                base.append(('petro_import_batch', '!=', False))
            moves = Move.search(base)
            # Match on partner + truck plate. The loadings report and customer
            # ledger use different sell prices, so amount matching is skipped.
            return moves.filtered(
                lambda m: not require_truck or self._ledger_move_has_plate(m, plate))

        # Priority 1: exact date
        candidates = _search_date(self.date)
        if not candidates:
            # Priority 2: ±1 day — covers billing-day vs loading-day differences
            for delta in (1, -1):
                candidates = _search_date(self.date + timedelta(days=delta))
                if candidates:
                    break
        return self._ledger_pick_best(candidates, self.amount_sell)

    def _ledger_find_vendor_bills(
            self, only_imported=True, require_truck=True, use_aliases=True):
        self.ensure_one()
        plate = self._ledger_plate()
        if require_truck and not plate:
            return self.env['account.move']

        supplier_amounts = self._ledger_supplier_amounts()
        if not supplier_amounts:
            return self.env['account.move']

        found = self.env['account.move']
        Move = self.env['account.move']
        for supplier_id, expected in supplier_amounts.items():
            supplier = self.env['res.partner'].browse(supplier_id)
            domain = self._ledger_base_domain('in_invoice', only_imported)
            domain.append(('partner_id', 'in', self._ledger_partner_match_ids(
                supplier, role='vendor', use_aliases=use_aliases)))
            candidates = self._ledger_filter_moves(
                Move.search(domain), plate, expected, require_truck)
            bill = self._ledger_pick_best(candidates, expected)
            if bill:
                found |= bill
        return found

    def _ledger_expected_bill_count(self):
        self.ensure_one()
        return len(self._ledger_supplier_amounts())

    def _ledger_link_state_value(self):
        self.ensure_one()
        invoices = self.ledger_move_ids.filtered(lambda m: m.move_type == 'out_invoice')
        bills = self.ledger_move_ids.filtered(lambda m: m.move_type == 'in_invoice')
        need_bills = self._ledger_expected_bill_count()
        has_bills = len(bills) >= need_bills if need_bills else True
        if self._ledger_skip_partner():
            if has_bills:
                return 'full'
            if bills:
                return 'partial'
            return 'none'
        has_inv = bool(invoices)
        if has_inv and has_bills:
            return 'full'
        if has_inv or bills:
            return 'partial'
        return 'none'

    def _ledger_apply_links(self, invoice, bills, mark_loaded=False):
        self.ensure_one()
        to_link = (invoice | bills).filtered(lambda m: not m.deal_id)
        if to_link:
            to_link.write({'deal_id': self.id})
        if mark_loaded and self.state == 'confirmed' and self._ledger_link_state_value() == 'full':
            self.state = 'loaded'

    def action_link_ledger_moves(
            self, only_imported=True, require_truck=True, mark_loaded=False,
            use_aliases=True):
        """Link imported ledger invoice/bill(s) to this deal (no new accounting)."""
        results = []
        for deal in self:
            if deal.state == 'cancel':
                results.append((deal, 'skipped', _('Cancelled deal.')))
                continue
            invoice, bills = deal._ledger_resolve_matches(
                only_imported, require_truck, use_aliases=use_aliases)
            if deal._ledger_skip_partner():
                invoice = self.env['account.move']
            if not invoice and not bills:
                hint = _('No matching vendor bill found.')
                if not deal._ledger_skip_partner():
                    hint = _('No matching imported invoice/bill found.')
                results.append((deal, 'miss', hint))
                continue
            deal._ledger_apply_links(invoice, bills, mark_loaded=mark_loaded)
            state = deal._ledger_link_state_value()
            msg_parts = []
            if invoice:
                msg_parts.append(_('invoice %s') % invoice.name)
            if bills:
                msg_parts.append(_('%d bill(s)') % len(bills))
            results.append((deal, state, ', '.join(msg_parts) or _('Linked')))
        return results

    def _ledger_link_hint(self, only_imported=True, require_truck=True, use_aliases=True):
        """Human-readable reason when automatic matching fails."""
        self.ensure_one()
        not_sold = self._ledger_skip_partner()
        plate = self._ledger_plate()
        if require_truck and not plate:
            return _('Set a truck plate on the deal.')
        Move = self.env['account.move']
        inv_domain = self._ledger_base_domain('out_invoice', only_imported)
        invs = Move.search(inv_domain)
        invs_plate = invs.filtered(lambda m: self._ledger_move_has_plate(m, plate))
        inv = self.env['account.move']
        if not not_sold:
            inv = self._ledger_find_customer_invoice(
                only_imported, require_truck, use_aliases=use_aliases)[:1]
            if not inv:
                if not invs_plate:
                    return _(
                        'No imported customer invoice on %(date)s with truck %(truck)s in '
                        'reference/narration.',
                        date=self.date,
                        truck=self.truck_id.name or plate,
                    )
                match_ids = self._ledger_partner_match_ids(
                    self.partner_id, role='customer', use_aliases=use_aliases)
                invs_amt = invs_plate.filtered(
                    lambda m: self._ledger_amount_ok(
                        abs(m.amount_total_signed), self.amount_sell))
                if invs_amt and not invs_amt.filtered(
                        lambda m: m.partner_id.id in match_ids):
                    other = invs_amt[0].partner_id.name
                    return _(
                        'Customer invoice %(inv)s is under “%(other)s”, not deal client '
                        '“%(deal)s”. Add a Ledger Partner Alias (Trading Desk → '
                        'Configuration) or align the deal contact.',
                        inv=invs_amt[0].name,
                        other=other,
                        deal=self.partner_id.name,
                    )
                if invs_plate and not invs_amt:
                    return _(
                        'Invoice(s) found for this truck/date but partner does not match '
                        '(deal client: %(deal)s).',
                        deal=self.partner_id.name,
                    )
                return _('No matching customer invoice.')
        hints = []
        if inv:
            hints.append(_('Customer: %s') % inv.name)
        for supplier, expected in self._ledger_supplier_amounts().items():
            partner = self.env['res.partner'].browse(supplier)
            bill_domain = self._ledger_base_domain('in_invoice', only_imported)
            bills = Move.search(bill_domain).filtered(
                lambda m, p=plate: self._ledger_move_has_plate(m, p))
            bills_sup = bills.filtered(
                lambda m, s=partner: m.partner_id.id in self._ledger_partner_match_ids(
                    s, role='vendor', use_aliases=use_aliases))
            if not bills_sup:
                hints.append(
                    _('No vendor bill for %(sup)s on %(date)s (truck %(truck)s).')
                    % {
                        'sup': partner.name,
                        'date': self.date,
                        'truck': self.truck_id.name or plate,
                    }
                )
            else:
                near = bills_sup.filtered(
                    lambda m, e=expected: abs(abs(m.amount_total_signed) - e)
                    <= self._ledger_amount_tolerance(e) * 4)
                if not near:
                    amt = abs(bills_sup[0].amount_total_signed)
                    hints.append(
                        _('Bill for %(sup)s: amount %(bill)s vs deal buy %(deal)s.')
                        % {'sup': partner.name, 'bill': amt, 'deal': expected}
                    )
        return ' '.join(hints)

    def _ledger_resolve_matches(
            self, only_imported=True, require_truck=True, use_aliases=True):
        """Return (customer_invoice, vendor_bills) preserving existing links."""
        self.ensure_one()
        existing = self.ledger_move_ids
        invoice = existing.filtered(lambda m: m.move_type == 'out_invoice')[:1]
        if not invoice:
            invoice = self._ledger_find_customer_invoice(
                only_imported, require_truck, use_aliases=use_aliases)[:1]
        linked_bills = existing.filtered(lambda m: m.move_type == 'in_invoice')
        need = self._ledger_expected_bill_count()
        if len(linked_bills) < need:
            found = self._ledger_find_vendor_bills(
                only_imported, require_truck, use_aliases=use_aliases)
            bills = linked_bills | found.filtered(lambda m: m.id not in linked_bills.ids)
        else:
            bills = linked_bills
        return invoice, bills

    def action_unlink_ledger_moves(self):
        for deal in self:
            if deal.ledger_move_ids:
                deal.ledger_move_ids.write({'deal_id': False})
        return True

    def action_open_ledger_link_wizard(self):
        self.ensure_one()
        ctx = {
            'default_deal_ids': [(6, 0, self.ids)],
            'default_date_from': self.date,
            'default_date_to': self.date,
        }
        if self.is_not_sold:
            ctx['default_only_imported'] = False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Link Vendor Bill') if self.is_not_sold else _('Link Ledger Documents'),
            'res_model': 'petroleum.deal.ledger.link',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }
