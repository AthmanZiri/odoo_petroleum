from odoo import _, fields, models
from odoo.exceptions import UserError


class PetroleumLedgerReconcile(models.TransientModel):
    _name = 'petroleum.ledger.reconcile'
    _description = 'Auto-offset invoices and payments (FIFO)'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    reconcile_customers = fields.Boolean(string='Customers (receivable)', default=True)
    reconcile_suppliers = fields.Boolean(string='Suppliers (payable)', default=True)
    partner_ids = fields.Many2many(
        'res.partner', string='Partners',
        help='Leave empty to offset every partner with open invoices and payments.')
    only_imported = fields.Boolean(
        string='Only imported entries', default=False,
        help='Limit to journal entries tagged by the Petroleum Data Import wizard.')
    dry_run = fields.Boolean(
        string='Dry run (report only)', default=False,
        help='Preview FIFO matches without posting reconciliations.')

    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    result_html = fields.Html(readonly=True)

    def _account_types(self, side):
        return ('asset_receivable',) if side == 'ar' else ('liability_payable',)

    def _partner_ids(self):
        if not self.partner_ids:
            return None
        return self.env['account.move.line']._petro_commercial_partner_ids(
            self.partner_ids)

    def action_reconcile(self):
        self.ensure_one()
        if not self.reconcile_customers and not self.reconcile_suppliers:
            raise UserError(_('Select at least customers or suppliers to reconcile.'))

        Line = self.env['account.move.line']
        partner_ids = self._partner_ids()
        report = []
        total_pairs = 0
        all_errors = []

        for side, label, enabled in (
            ('ar', _('Customers'), self.reconcile_customers),
            ('ap', _('Suppliers'), self.reconcile_suppliers),
        ):
            if not enabled:
                continue
            stats = Line._petro_fifo_offset(
                self.company_id,
                account_types=self._account_types(side),
                partner_ids=partner_ids,
                only_imported=self.only_imported,
                dry_run=self.dry_run,
            )
            total_pairs += stats['matches']
            all_errors.extend(stats['errors'])
            report.append(
                '<li><b>%s</b>: %d partner(s), %d FIFO match(es); '
                'unreconciled lines <b>%d → %d</b></li>'
                % (label, stats['partners'], stats['matches'],
                   stats['before'], stats['after'])
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
