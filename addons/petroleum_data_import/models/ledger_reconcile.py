import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PetroleumLedgerReconcile(models.TransientModel):
    _name = 'petroleum.ledger.reconcile'
    _description = 'Reconcile Imported Ledger Entries (FIFO)'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    reconcile_customers = fields.Boolean(string='Customers (receivable)', default=True)
    reconcile_suppliers = fields.Boolean(string='Suppliers (payable)', default=True)
    only_imported = fields.Boolean(
        string='Only imported entries', default=True,
        help='Limit to journal entries tagged by the Petroleum Data Import wizard.')
    dry_run = fields.Boolean(
        string='Dry run (report only)', default=False,
        help='Preview FIFO matches without posting reconciliations.')

    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    result_html = fields.Html(readonly=True)

    # ------------------------------------------------------------------
    def _account_type(self, side):
        return 'asset_receivable' if side == 'ar' else 'liability_payable'

    def _partner_domain(self, side):
        if side == 'ar':
            return [('customer_rank', '>', 0), ('parent_id', '=', False)]
        return [('supplier_rank', '>', 0), ('parent_id', '=', False)]

    def _line_domain(self, partner, side):
        domain = [
            ('partner_id', '=', partner.id),
            ('account_id.account_type', '=', self._account_type(side)),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('company_id', '=', self.company_id.id),
        ]
        if self.only_imported:
            domain.append(('move_id.petro_import_batch', '!=', False))
        return domain

    def _fifo_reconcile_partner(self, partner, side):
        """Match open credits against oldest open debits (FIFO by date)."""
        Line = self.env['account.move.line']
        lines = Line.search(self._line_domain(partner, side), order='date asc, id asc')
        positives = lines.filtered(lambda l: l.amount_residual > 0)
        negatives = lines.filtered(lambda l: l.amount_residual < 0)
        pairs = 0
        errors = []

        if self.dry_run:
            pos_left = {l.id: l.amount_residual for l in positives}
            for neg in negatives:
                neg_left = -neg.amount_residual
                for pos in positives:
                    if neg_left <= 0:
                        break
                    avail = pos_left.get(pos.id, 0.0)
                    if avail <= 0:
                        continue
                    take = min(avail, neg_left)
                    pos_left[pos.id] = avail - take
                    neg_left -= take
                    pairs += 1
            return pairs, errors

        for neg in negatives:
            while not self.company_id.currency_id.is_zero(neg.amount_residual):
                neg.invalidate_recordset(['amount_residual', 'reconciled'])
                pos = Line.search(
                    self._line_domain(partner, side)
                    + [('amount_residual', '>', 0), ('account_id', '=', neg.account_id.id)],
                    order='date asc, id asc', limit=1,
                )
                if not pos:
                    break
                try:
                    (neg | pos).reconcile()
                    pairs += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append('%s / %s: %s' % (partner.display_name, neg.move_id.name, exc))
                    _logger.exception('FIFO reconcile failed for %s', partner.display_name)
                    break
        return pairs, errors

    def _unreconciled_count(self, side):
        partners = self.env['res.partner'].search(self._partner_domain(side))
        domain = [
            ('partner_id', 'in', partners.ids),
            ('account_id.account_type', '=', self._account_type(side)),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('company_id', '=', self.company_id.id),
        ]
        if self.only_imported:
            domain.append(('move_id.petro_import_batch', '!=', False))
        return self.env['account.move.line'].search_count(domain)

    def action_reconcile(self):
        self.ensure_one()
        if not self.reconcile_customers and not self.reconcile_suppliers:
            raise UserError(_('Select at least customers or suppliers to reconcile.'))

        report = []
        total_pairs = 0
        all_errors = []

        for side, label, enabled in (
            ('ar', _('Customers'), self.reconcile_customers),
            ('ap', _('Suppliers'), self.reconcile_suppliers),
        ):
            if not enabled:
                continue
            before = self._unreconciled_count(side)
            partners = self.env['res.partner'].search(self._partner_domain(side))
            side_pairs = 0
            processed = 0
            for partner in partners:
                pairs, errors = self._fifo_reconcile_partner(partner, side)
                if pairs:
                    processed += 1
                    side_pairs += pairs
                all_errors.extend(errors)
            after = self._unreconciled_count(side)
            total_pairs += side_pairs
            report.append(
                '<li><b>%s</b>: %d partner(s), %d FIFO match(es); '
                'unreconciled lines <b>%d → %d</b></li>'
                % (label, processed, side_pairs, before, after)
            )

        mode = _('Dry run') if self.dry_run else _('Done')
        html = (
            '<h4>%s</h4><ul>%s</ul><p>Total FIFO matches: <b>%d</b></p>'
            % (mode, ''.join(report), total_pairs)
        )
        if all_errors:
            html += '<p style="color:#c0392b"><b>Errors (%d):</b><br/>%s</p>' % (
                len(all_errors), '<br/>'.join(all_errors[:20]))
        self.write({'state': 'done', 'result_html': html})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
