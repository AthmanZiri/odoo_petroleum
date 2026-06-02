from odoo import _, fields, models
from odoo.exceptions import UserError


class PetroleumDealLedgerLink(models.TransientModel):
    _name = 'petroleum.deal.ledger.link'
    _description = 'Link Deals to Imported Ledger Invoices/Bills'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    deal_ids = fields.Many2many(
        'petroleum.deal', string='Deals',
        help='Leave empty to process all eligible deals in the date range.')
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    only_imported = fields.Boolean(
        string='Only petroleum import batch', default=True,
        help='Match only moves tagged by the Petroleum Data Import wizard.')
    require_truck = fields.Boolean(
        string='Require truck plate on document', default=True,
        help='Reference or narration must contain the deal truck plate.')
    mark_as_loaded = fields.Boolean(
        string='Mark fully linked deals as Loaded', default=True,
        help='Moves confirmed deals to Loaded when customer invoice and all '
             'supplier bills are linked (does not post new invoices).')
    dry_run = fields.Boolean(
        string='Dry run (preview only)', default=False,
        help='Show matches without writing deal_id on journal entries.')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    result_html = fields.Html(readonly=True)

    def _deal_candidates(self):
        self.ensure_one()
        if self.deal_ids:
            deals = self.deal_ids.filtered(
                lambda d: d.company_id == self.company_id and d.state != 'cancel')
        else:
            domain = [
                ('company_id', '=', self.company_id.id),
                ('state', 'in', ('confirmed', 'loaded', 'done')),
            ]
            if self.date_from:
                domain.append(('date', '>=', self.date_from))
            if self.date_to:
                domain.append(('date', '<=', self.date_to))
            deals = self.env['petroleum.deal'].search(domain, order='date desc, id desc')
        if self.require_truck:
            deals = deals.filtered('truck_id')
        return deals

    def action_link(self):
        self.ensure_one()
        deals = self._deal_candidates()
        if not deals:
            raise UserError(_('No deals to process. Select deals or widen the date range.'))

        full = partial = missed = skipped = 0
        rows = []

        for deal in deals:
            if deal._ledger_skip_partner():
                skipped += 1
                rows.append((deal.name, 'skipped', _('NOT SOLD'), True))
                continue

            inv, bill_set = deal._ledger_resolve_matches(
                self.only_imported, self.require_truck)
            need = deal._ledger_expected_bill_count()

            if not inv and not bill_set:
                missed += 1
                detail = _('No match (customer + %d supplier(s)).') % need
                rows.append((deal.name, 'miss', detail, True))
                continue

            preview_state = 'full'
            if not inv or len(bill_set) < need:
                preview_state = 'partial'

            parts = []
            if inv:
                parts.append(_('INV %s') % inv.name)
            if bill_set:
                parts.append(_('%d bill(s)') % len(bill_set))
            detail = ', '.join(parts)

            if not self.dry_run:
                deal._ledger_apply_links(inv, bill_set, self.mark_as_loaded)
                preview_state = deal._ledger_link_state_value()

            if preview_state == 'full':
                full += 1
            elif preview_state == 'partial':
                partial += 1
            else:
                missed += 1
            rows.append((deal.name, preview_state, detail, preview_state == 'miss'))

        mode = _('Dry run') if self.dry_run else _('Done')
        head = (
            '<div><h3>%s — Link deals to ledger</h3>'
            '<p>Processed <b>%d</b> deal(s): '
            '<b>%d</b> fully linked, <b>%d</b> partial, '
            '<b>%d</b> no match, <b>%d</b> skipped.</p>'
        ) % (mode, len(deals), full, partial, missed, skipped)

        if self.dry_run:
            head += '<p><i>No changes saved. Uncheck Dry run and run again to apply.</i></p>'

        trs = []
        for name, status, detail, warn in rows[:80]:
            style = "background:#ffd5d5;" if warn else ''
            trs.append(
                "<tr style='%s'><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (style, name, status, detail))
        if len(rows) > 80:
            trs.append("<tr><td colspan='3'>… %d more</td></tr>" % (len(rows) - 80))

        table = (
            "<table class='table table-sm' style='width:100%%'>"
            "<thead><tr><th>Deal</th><th>Status</th><th>Matched documents</th></tr>"
            "</thead><tbody>%s</tbody></table></div>"
        ) % ''.join(trs)

        self.write({'state': 'done', 'result_html': head + table})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
