from odoo import api, fields, models
from odoo.tools.float_utils import float_compare


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    is_daily_position_po = fields.Boolean(
        string='Daily Position PO', default=False, index=True,
        help='Bulk purchase order created from the morning position board.')
    daily_position_date = fields.Date(string='Position Date', index=True)

    @api.model
    def _petro_repair_vendor_bill_links(self):
        """Relink price-adjustment and orphan extra lines; recompute billed qty.

        Called from the 19.0.1.0.37 migration. Safe to re-run.
        """
        stats = {
            'price_refunds_tagged': self._petro_tag_price_only_refunds(),
            'adjustments_linked': self._petro_relink_price_adjustment_bills(),
            'orphan_lines_linked': self._petro_relink_orphan_vendor_bill_lines(),
            'draft_bills_created': self._petro_create_draft_bills_for_cancelled_only(),
        }
        return stats

    @api.model
    def _petro_relink_price_adjustment_bills(self):
        """Set purchase_line_id on supplier_buy documents from invoice_origin."""
        moves = self.env['account.move'].search([
            ('petro_price_adjustment', '=', 'supplier_buy'),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('state', '!=', 'cancel'),
        ])
        linked = 0
        for move in moves:
            lines = move.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product'
                and not line.purchase_line_id)
            if not lines:
                continue
            po = self._petro_po_from_origin(move.invoice_origin)
            if not po:
                continue
            for line in lines:
                po_line = po._petro_matching_order_line(
                    product=line.product_id or lines.product_id[:1],
                    old_price=move.petro_old_price,
                    scope=move.petro_adjustment_scope,
                )
                if not po_line:
                    continue
                line._petro_write_purchase_link({
                    'purchase_line_id': po_line.id,
                })
                linked += 1
        return linked

    @api.model
    def _petro_relink_orphan_vendor_bill_lines(self):
        """Attach extra bill lines (no PO line) to open PO lines of the origin PO.

        Typical case: remaining litres typed onto a posted bill at a new unit
        price instead of billed against the PO line. Linking clears phantom
        qty_to_invoice without posting another bill.
        """
        lines = self.env['account.move.line'].search([
            ('display_type', '=', 'product'),
            ('purchase_line_id', '=', False),
            ('move_id.move_type', '=', 'in_invoice'),
            ('move_id.state', '=', 'posted'),
            ('move_id.petro_price_adjustment', '=', False),
            ('move_id.payment_state', 'not in', ('paid', 'in_payment', 'reversed')),
        ])
        if 'petro_import_batch' in self.env['account.move']._fields:
            lines = lines.filtered(lambda line: not line.move_id.petro_import_batch)
        linked = 0
        used_po_lines = self.env['purchase.order.line']
        for line in lines.sorted('id'):
            po = self._petro_po_from_origin(
                line.move_id.invoice_origin or line.move_id.ref)
            if not po:
                continue
            candidates = po.order_line.filtered(
                lambda po_line: not po_line.display_type
                and po_line.qty_to_invoice > 0
                and po_line not in used_po_lines)
            if line.product_id:
                by_product = candidates.filtered(
                    lambda po_line: po_line.product_id == line.product_id)
                if by_product:
                    candidates = by_product
            po_line = candidates.filtered(
                lambda cand: not float_compare(
                    cand.qty_to_invoice, line.quantity,
                    precision_rounding=cand.product_uom_id.rounding or 0.01)
            )[:1] or candidates[:1]
            if not po_line:
                continue
            vals = {'purchase_line_id': po_line.id}
            if not line.product_id and po_line.product_id:
                vals['product_id'] = po_line.product_id.id
            line._petro_write_purchase_link(vals)
            used_po_lines |= po_line
            linked += 1
        return linked

    @api.model
    def _petro_create_draft_bills_for_cancelled_only(self):
        """Draft a replacement bill when the only vendor bill on a PO is cancelled."""
        orders = self.search([
            ('state', 'in', ('purchase', 'done')),
            ('invoice_status', '=', 'to invoice'),
        ])
        created = 0
        for order in orders:
            bills = order.invoice_ids
            if not bills:
                continue
            if bills.filtered(lambda move: move.state != 'cancel'):
                continue
            if not order.order_line.filtered(
                    lambda line: not line.display_type and line.qty_to_invoice):
                continue
            order.with_context(auto_bill_on_confirm=True).action_create_invoice()
            created += 1
        return created

    @api.model
    def _petro_tag_price_only_refunds(self):
        """Mark vendor refunds whose unit price is a delta, not a product price.

        Untagged price CNs still reverse qty_invoiced because they keep
        purchase_line_id. A KES 0.50–1.00 credit on a ~KES 200 fuel line is a
        price adjustment, not a quantity return.
        """
        refunds = self.env['account.move'].search([
            ('move_type', '=', 'in_refund'),
            ('state', '=', 'posted'),
            ('petro_price_adjustment', '=', False),
        ])
        tagged = 0
        for move in refunds:
            lines = move.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product'
                and line.purchase_line_id
                and line.purchase_line_id.price_unit)
            if not lines:
                continue
            if any(
                    float_compare(
                        line.price_unit,
                        line.purchase_line_id.price_unit * 0.1,
                        precision_digits=2) >= 0
                    for line in lines):
                continue
            first = lines[0]
            move.write({
                'petro_price_adjustment': 'supplier_buy',
                'petro_adjustment_scope': move.petro_adjustment_scope or 'sold',
                'petro_old_price': first.purchase_line_id.price_unit,
                'petro_new_price': (
                    first.purchase_line_id.price_unit - first.price_unit),
            })
            tagged += 1
        return tagged

    @api.model
    def _petro_po_from_origin(self, origin):
        if not origin:
            return self.browse()
        token = origin.split(',')[0].strip().split()[0]
        if not token:
            return self.browse()
        return self.search([('name', '=', token)], limit=1)

    def _petro_matching_order_line(self, product=None, old_price=None, scope=None):
        self.ensure_one()
        lines = self.order_line.filtered(lambda line: not line.display_type)
        if product:
            lines = lines.filtered(lambda line: line.product_id == product)
        if old_price and lines:
            priced = lines.filtered(
                lambda line: not float_compare(
                    line.price_unit, old_price,
                    precision_digits=self.currency_id.decimal_places or 2))
            if priced:
                lines = priced
        if scope == 'sold':
            billed = lines.filtered(lambda line: line.qty_invoiced > 0)
            if billed:
                lines = billed
        elif scope == 'remaining':
            open_lines = lines.filtered(lambda line: line.qty_to_invoice > 0)
            if open_lines:
                lines = open_lines
        return lines[:1]


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    petroleum_position_line_id = fields.Many2one(
        'petroleum.daily.position.line', string='Position Line', index=True, copy=False)

    def _get_invoice_lines(self):
        """Price-only supplier CN/DN must not reverse billed litres."""
        lines = super()._get_invoice_lines()
        return lines.filtered(
            lambda line: line.move_id.petro_price_adjustment != 'supplier_buy')

    @api.depends(
        'invoice_lines.move_id.state',
        'invoice_lines.move_id.petro_price_adjustment',
        'invoice_lines.quantity',
        'qty_received',
        'product_uom_qty',
        'order_id.state',
    )
    def _compute_qty_invoiced(self):
        return super()._compute_qty_invoiced()
