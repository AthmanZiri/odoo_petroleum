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

    def _ledger_find_customer_invoice(self, only_imported=True, require_truck=True):
        self.ensure_one()
        if self._ledger_skip_partner():
            return self.env['account.move']
        plate = self._ledger_plate()
        if require_truck and not plate:
            return self.env['account.move']

        domain = self._ledger_base_domain('out_invoice', only_imported)
        domain.append(('partner_id', 'child_of', self.partner_id.commercial_partner_id.id))
        candidates = self.env['account.move'].search(domain)
        candidates = candidates.filtered(
            lambda m: self._ledger_move_has_plate(m, plate)
            and self._ledger_amount_ok(abs(m.amount_total_signed), self.amount_sell))
        return self._ledger_pick_best(candidates, self.amount_sell)

    def _ledger_find_vendor_bills(self, only_imported=True, require_truck=True):
        self.ensure_one()
        plate = self._ledger_plate()
        if require_truck and not plate:
            return self.env['account.move']

        supplier_amounts = self._ledger_supplier_amounts()
        if not supplier_amounts:
            return self.env['account.move']

        found = self.env['account.move']
        for supplier_id, expected in supplier_amounts.items():
            domain = self._ledger_base_domain('in_invoice', only_imported)
            domain.append(('partner_id', 'child_of', supplier_id))
            candidates = self.env['account.move'].search(domain)
            candidates = candidates.filtered(
                lambda m, p=plate, e=expected: self._ledger_move_has_plate(m, p)
                and self._ledger_amount_ok(abs(m.amount_total_signed), e))
            bill = self._ledger_pick_best(candidates, expected)
            if bill:
                found |= bill
        return found

    def _ledger_expected_bill_count(self):
        self.ensure_one()
        return len(self._ledger_supplier_amounts())

    def _ledger_link_state_value(self):
        self.ensure_one()
        if self._ledger_skip_partner():
            return 'none'
        invoices = self.ledger_move_ids.filtered(lambda m: m.move_type == 'out_invoice')
        bills = self.ledger_move_ids.filtered(lambda m: m.move_type == 'in_invoice')
        need_bills = self._ledger_expected_bill_count()
        has_inv = bool(invoices)
        has_bills = len(bills) >= need_bills if need_bills else True
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

    def action_link_ledger_moves(self, only_imported=True, require_truck=True, mark_loaded=False):
        """Link imported ledger invoice/bill(s) to this deal (no new accounting)."""
        results = []
        for deal in self:
            if deal.state == 'cancel':
                results.append((deal, 'skipped', _('Cancelled deal.')))
                continue
            if deal._ledger_skip_partner():
                results.append((deal, 'skipped', _('NOT SOLD placeholder — no ledger link.')))
                continue
            invoice, bills = deal._ledger_resolve_matches(only_imported, require_truck)
            if not invoice and not bills:
                results.append((deal, 'miss', _('No matching imported invoice/bill found.')))
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

    def _ledger_resolve_matches(self, only_imported=True, require_truck=True):
        """Return (customer_invoice, vendor_bills) preserving existing links."""
        self.ensure_one()
        existing = self.ledger_move_ids
        invoice = existing.filtered(lambda m: m.move_type == 'out_invoice')[:1]
        if not invoice:
            invoice = self._ledger_find_customer_invoice(only_imported, require_truck)[:1]
        linked_bills = existing.filtered(lambda m: m.move_type == 'in_invoice')
        need = self._ledger_expected_bill_count()
        if len(linked_bills) < need:
            found = self._ledger_find_vendor_bills(only_imported, require_truck)
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
        return {
            'type': 'ir.actions.act_window',
            'name': _('Link Ledger Documents'),
            'res_model': 'petroleum.deal.ledger.link',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_deal_ids': [(6, 0, self.ids)],
                'default_date_from': self.date,
                'default_date_to': self.date,
            },
        }
