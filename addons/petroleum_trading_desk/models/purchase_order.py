from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
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

    def _daily_position_quantity_bills(self):
        """Vendor bills/refunds that represent litres, not price-only CN/DN."""
        self.ensure_one()
        return self.invoice_ids.filtered(
            lambda move: move.move_type in ('in_invoice', 'in_refund')
            and move.state != 'cancel'
            and not move.petro_price_adjustment
        )

    def _daily_position_rewritable_bill(self):
        """Single unpaid quantity bill that can still be rewritten in place.

        Paid, locked, reversed, or already-corrected (extra bills / refunds /
        supplier price CN/DN) documents are left alone; the caller posts a
        delta bill instead.
        """
        self.ensure_one()
        qty_bills = self._daily_position_quantity_bills()
        invoices = qty_bills.filtered(lambda move: move.move_type == 'in_invoice')
        refunds = qty_bills.filtered(lambda move: move.move_type == 'in_refund')
        if refunds or len(invoices) != 1:
            return self.env['account.move']
        if self.invoice_ids.filtered(
                lambda move: move.petro_price_adjustment == 'supplier_buy'
                and move.state != 'cancel'):
            return self.env['account.move']
        bill = invoices
        if bill.state == 'draft':
            return bill
        if bill.state != 'posted':
            return self.env['account.move']
        if bill.payment_state not in ('not_paid',):
            return self.env['account.move']
        return bill

    def _daily_position_bill_matches_po(self, bill):
        """True when the bill's product lines match PO qty and unit price."""
        self.ensure_one()
        if not bill:
            return False
        precision = self.currency_id.decimal_places or 2
        po_lines = self.order_line.filtered(lambda line: not line.display_type)
        billed_lines = bill.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product')
        extra = billed_lines.filtered(
            lambda line: line.purchase_line_id and line.purchase_line_id not in po_lines)
        if extra:
            return False
        for po_line in po_lines:
            rounding = po_line.product_uom_id.rounding or 0.01
            matches = billed_lines.filtered(
                lambda line: line.purchase_line_id == po_line
                or (not line.purchase_line_id and line.product_id == po_line.product_id))
            billed_qty = sum(matches.mapped('quantity'))
            if float_compare(
                    billed_qty, po_line.product_qty,
                    precision_rounding=rounding) != 0:
                return False
            if po_line.product_qty and not matches:
                return False
            if matches and float_compare(
                    matches[0].price_unit, po_line.price_unit,
                    precision_digits=precision) != 0:
                return False
        return True

    def _stamp_daily_position_bill(self, bills):
        self.ensure_one()
        if not bills:
            return
        invoice_date = self.daily_position_date or fields.Date.context_today(self)
        bills.write({
            'invoice_date': invoice_date,
            'ref': self.name,
            'invoice_origin': self.name,
        })

    def _reset_vendor_bill_to_draft(self, bill):
        """Reset a posted bill to draft, or False when lock/payment blocks it."""
        if bill.state == 'draft':
            return True
        try:
            with self.env.cr.savepoint():
                bill.button_draft()
                if bill.state != 'draft':
                    raise UserError(_('Vendor bill could not be reset to draft.'))
        except (UserError, ValidationError):
            return False
        return bill.state == 'draft'

    def _rewrite_daily_position_bill(self, bill):
        """Replace the bill's product lines so they match current PO lines."""
        self.ensure_one()
        if not self._reset_vendor_bill_to_draft(bill):
            return self._post_daily_position_delta_bills()
        product_lines = bill.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product')
        used = self.env['account.move.line']
        commands = []
        for po_line in self.order_line.filtered(lambda line: not line.display_type):
            rounding = po_line.product_uom_id.rounding or 0.01
            if float_compare(po_line.product_qty, 0.0, precision_rounding=rounding) <= 0:
                continue
            vals = po_line.with_context(
                auto_bill_on_confirm=True)._prepare_account_move_line(bill)
            vals['quantity'] = po_line.product_qty
            vals['price_unit'] = po_line.price_unit
            match = product_lines.filtered(
                lambda line: line.purchase_line_id == po_line)[:1]
            if not match:
                match = product_lines.filtered(
                    lambda line: line.product_id == po_line.product_id
                    and line not in used)[:1]
            if match:
                match.write({
                    'product_id': po_line.product_id.id,
                    'name': vals.get('name') or po_line.name,
                    'quantity': po_line.product_qty,
                    'price_unit': po_line.price_unit,
                    'purchase_line_id': po_line.id,
                    'product_uom_id': po_line.product_uom_id.id,
                    'tax_ids': vals.get('tax_ids') or [
                        fields.Command.set(po_line.tax_ids.ids)],
                })
                used |= match
            else:
                commands.append(fields.Command.create(vals))
        leftover = product_lines - used
        line_commands = [
            fields.Command.delete(line.id) for line in leftover
        ] + commands
        if line_commands:
            bill.write({'invoice_line_ids': line_commands})
        self._stamp_daily_position_bill(bill)
        bill.action_post()
        return bill

    def _post_daily_position_delta_bills(self):
        """Bill remaining qty_to_invoice (extra litres) or refund over-billing."""
        self.ensure_one()
        self.order_line._compute_qty_invoiced()
        open_lines = self.order_line.filtered(
            lambda line: not line.display_type and float_compare(
                line.qty_to_invoice, 0.0,
                precision_rounding=line.product_uom_id.rounding or 0.01) != 0)
        if not open_lines:
            return self.env['account.move']
        drafts = self.invoice_ids.filtered(
            lambda move: move.state == 'draft'
            and move.move_type in ('in_invoice', 'in_refund')
            and not move.petro_price_adjustment)
        if not drafts:
            self.with_context(auto_bill_on_confirm=True).action_create_invoice()
            drafts = self.invoice_ids.filtered(
                lambda move: move.state == 'draft'
                and move.move_type in ('in_invoice', 'in_refund')
                and not move.petro_price_adjustment)
        if drafts:
            self._stamp_daily_position_bill(drafts)
            drafts.action_post()
        return drafts

    def _create_daily_position_qty_refund(self, po_line, quantity):
        """Post a quantity credit note so billed litres can fall with the PO."""
        self.ensure_one()
        rounding = po_line.product_uom_id.rounding or 0.01
        if float_compare(quantity, 0.0, precision_rounding=rounding) <= 0:
            return self.env['account.move']
        vals = po_line.with_context(
            auto_bill_on_confirm=True)._prepare_account_move_line()
        vals['quantity'] = quantity
        vals['price_unit'] = po_line.price_unit
        refund = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_date': self.daily_position_date or fields.Date.context_today(self),
            'invoice_line_ids': [fields.Command.create(vals)],
        })
        self._stamp_daily_position_bill(refund)
        refund.action_post()
        return refund

    def _prepare_daily_position_qty_decrease(self, po_line, new_qty):
        """Drop billed litres before the PO qty write when it would go below invoiced.

        Unpaid single bills are reset to draft (qty_invoiced ignores drafts).
        Paid or locked bills get a quantity refund first so Odoo allows the
        lower ordered qty.
        """
        self.ensure_one()
        rounding = po_line.product_uom_id.rounding or 0.01
        po_line._compute_qty_invoiced()
        invoiced = po_line.qty_invoiced
        if float_compare(new_qty, invoiced, precision_rounding=rounding) >= 0:
            return
        rewritable = self._daily_position_rewritable_bill()
        if rewritable and self._reset_vendor_bill_to_draft(rewritable):
            po_line.invalidate_recordset(['qty_invoiced', 'qty_to_invoice'])
            po_line._compute_qty_invoiced()
            return
        self._create_daily_position_qty_refund(po_line, invoiced - new_qty)
        po_line.invalidate_recordset(['qty_invoiced', 'qty_to_invoice'])
        po_line._compute_qty_invoiced()

    def _sync_daily_position_vendor_bills(self):
        """Keep daily-position vendor bills aligned with the current PO lines.

        Unpaid single bills are rewritten in place so the morning bulk buy
        stays one document per supplier. Paid, locked, or price-adjusted POs
        get a delta vendor bill or refund for the quantity gap instead.
        Idempotent: matching bills are left untouched (draft ones are posted).
        """
        for order in self.filtered('is_daily_position_po'):
            qty_bills = order._daily_position_quantity_bills()
            if not qty_bills:
                order._auto_create_vendor_bill()
            rewritable = order._daily_position_rewritable_bill()
            if rewritable:
                if not order._daily_position_bill_matches_po(rewritable):
                    order._rewrite_daily_position_bill(rewritable)
                elif rewritable.state == 'draft':
                    order._stamp_daily_position_bill(rewritable)
                    rewritable.action_post()
            else:
                order._post_daily_position_delta_bills()


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
