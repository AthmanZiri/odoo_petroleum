from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PetroleumDealLedgerLinkLine(models.TransientModel):
    _name = 'petroleum.deal.ledger.link.line'
    _description = 'Manual ledger link line'
    _order = 'deal_date desc, deal_id desc'

    link_id = fields.Many2one(
        'petroleum.deal.ledger.link', required=True, ondelete='cascade')
    company_id = fields.Many2one(
        related='link_id.company_id', store=True, readonly=True)
    deal_id = fields.Many2one(
        'petroleum.deal', required=True, ondelete='cascade',
        domain="[('company_id', '=', company_id), ('state', '!=', 'cancel')]")
    deal_date = fields.Date(related='deal_id.date', string='Date')
    partner_name = fields.Char(related='deal_id.partner_id.name', string='Client')
    truck_name = fields.Char(related='deal_id.truck_id.name', string='Truck')
    amount_sell = fields.Monetary(
        related='deal_id.amount_sell', currency_field='currency_id', string='Sell')
    amount_buy = fields.Monetary(
        related='deal_id.amount_buy', currency_field='currency_id', string='Buy')
    currency_id = fields.Many2one(related='deal_id.currency_id')
    customer_invoice_id = fields.Many2one(
        'account.move', string='Customer invoice',
        domain="[('company_id', '=', company_id), ('move_type', '=', 'out_invoice'), "
               "('state', '=', 'posted')]",
    )
    vendor_bill_ids = fields.Many2many(
        'account.move',
        'petroleum_deal_ledger_link_line_bill_rel',
        'line_id', 'move_id',
        string='Vendor bills',
        domain="[('company_id', '=', company_id), ('move_type', '=', 'in_invoice'), "
               "('state', '=', 'posted')]",
    )
    use_manual = fields.Boolean(
        compute='_compute_use_manual',
        help='This row uses manually selected documents instead of automatic matching.',
    )

    @api.depends('customer_invoice_id', 'vendor_bill_ids')
    def _compute_use_manual(self):
        for line in self:
            line.use_manual = bool(line.customer_invoice_id or line.vendor_bill_ids)

    def _check_manual_moves(self):
        for line in self:
            deal = line.deal_id
            moves = line.customer_invoice_id | line.vendor_bill_ids
            for move in moves:
                if move.company_id != deal.company_id:
                    raise UserError(_(
                        '%(move)s belongs to another company.',
                        move=move.display_name,
                    ))
                if move.state != 'posted':
                    raise UserError(_(
                        '%(move)s must be posted before linking.',
                        move=move.display_name,
                    ))
                if move.deal_id and move.deal_id != deal:
                    raise UserError(_(
                        '%(move)s is already linked to %(deal)s.',
                        move=move.display_name,
                        deal=move.deal_id.display_name,
                    ))
                if line.link_id.only_imported and not getattr(move, 'petro_import_batch', False):
                    raise UserError(_(
                        '%(move)s is not from a petroleum import batch. '
                        'Uncheck “Only petroleum import batch” or pick another document.',
                        move=move.display_name,
                    ))
            if line.customer_invoice_id and line.customer_invoice_id.move_type != 'out_invoice':
                raise UserError(_('Pick a customer invoice for %(deal)s.', deal=deal.name))
            for bill in line.vendor_bill_ids:
                if bill.move_type != 'in_invoice':
                    raise UserError(_('Vendor bills must be supplier bills for %(deal)s.', deal=deal.name))

    def _manual_invoice_and_bills(self):
        """Return (invoice, bills) from manual picks only."""
        self.ensure_one()
        invoice = self.customer_invoice_id
        if self.deal_id.is_not_sold:
            invoice = self.env['account.move']
        return invoice, self.vendor_bill_ids


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
    line_ids = fields.One2many(
        'petroleum.deal.ledger.link.line', 'link_id', string='Manual links')
    only_imported = fields.Boolean(
        string='Only petroleum import batch', default=True,
        help='Match only moves tagged by the Petroleum Data Import wizard.')
    require_truck = fields.Boolean(
        string='Require truck plate on document', default=True,
        help='Reference or narration must contain the deal truck plate.')
    use_partner_aliases = fields.Boolean(
        string='Use ledger partner aliases', default=True,
        help='Also match imported documents on contacts configured under '
             'Trading Desk → Configuration → Ledger Partner Aliases. '
             'The deal must still use the deal contact (Odoo partner tree).')
    mark_as_loaded = fields.Boolean(
        string='Mark fully linked deals as Loaded', default=True,
        help='Moves confirmed deals to Loaded when customer invoice and all '
             'supplier bills are linked (does not post new invoices).')
    dry_run = fields.Boolean(
        string='Dry run (preview only)', default=False,
        help='Show matches without writing deal_id on journal entries.')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    result_html = fields.Html(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'line_ids' not in fields_list:
            return res
        deals = self.env['petroleum.deal']
        deal_cmds = res.get('deal_ids') or self.env.context.get('default_deal_ids')
        if deal_cmds:
            if isinstance(deal_cmds, list) and deal_cmds and isinstance(deal_cmds[0], (list, tuple)):
                if deal_cmds[0][0] == 6:
                    deals = deals.browse(deal_cmds[0][2])
            else:
                deals = deals.browse(deal_cmds)
        if deals:
            res['line_ids'] = [(0, 0, {'deal_id': d.id}) for d in deals.exists()]
        return res

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

    def _sync_lines(self):
        """Align manual link rows with the current deal scope."""
        self.ensure_one()
        deals = self._deal_candidates()
        existing = {line.deal_id.id: line for line in self.line_ids}
        commands = []
        for deal in deals:
            if deal.id in existing:
                continue
            commands.append((0, 0, {'deal_id': deal.id}))
        for deal_id, line in existing.items():
            if deal_id not in deals.ids:
                commands.append((2, line.id))
        if commands:
            self.write({'line_ids': commands})
        return True

    def action_sync_lines(self):
        self._sync_lines()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_suggest_matches(self):
        """Fill empty manual rows from automatic matching rules."""
        self.ensure_one()
        self._sync_lines()
        for line in self.line_ids:
            inv, bills = line.deal_id._ledger_resolve_matches(
                self.only_imported,
                self.require_truck,
                use_aliases=self.use_partner_aliases,
            )
            if not line.customer_invoice_id and inv and not line.deal_id.is_not_sold:
                line.customer_invoice_id = inv
            if not line.vendor_bill_ids and bills:
                line.vendor_bill_ids = bills
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_back_to_draft(self):
        self.write({'state': 'draft', 'result_html': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _resolve_for_deal(self, deal):
        """Automatic or manual match for one deal."""
        line = self.line_ids.filtered(lambda l: l.deal_id == deal)[:1]
        if line and line.use_manual:
            line._check_manual_moves()
            return line._manual_invoice_and_bills()
        return deal._ledger_resolve_matches(
            self.only_imported,
            self.require_truck,
            use_aliases=self.use_partner_aliases,
        )

    def _preview_state(self, deal, inv, bills):
        need = deal._ledger_expected_bill_count()
        if not inv and not bills:
            return 'miss'
        if deal._ledger_skip_partner():
            if need and len(bills) >= need:
                return 'full'
            if bills:
                return 'partial'
            return 'miss'
        if inv and (not need or len(bills) >= need):
            return 'full'
        if inv or bills:
            return 'partial'
        return 'miss'

    def action_link(self):
        self.ensure_one()
        self._sync_lines()
        deals = self._deal_candidates()
        if not deals:
            raise UserError(_('No deals to process. Select deals or widen the date range.'))

        full = partial = missed = skipped = 0
        rows = []

        for deal in deals:
            inv, bill_set = self._resolve_for_deal(deal)
            if deal._ledger_skip_partner():
                inv = self.env['account.move']
            need = deal._ledger_expected_bill_count()
            line = self.line_ids.filtered(lambda l: l.deal_id == deal)[:1]
            manual = line.use_manual if line else False

            if not inv and not bill_set:
                missed += 1
                detail = deal._ledger_link_hint(
                    self.only_imported, self.require_truck,
                    use_aliases=self.use_partner_aliases)
                if manual:
                    detail = _('Manual row: pick a customer invoice and/or vendor bill(s).')
                rows.append((deal.name, 'miss', detail, True))
                continue

            preview_state = self._preview_state(deal, inv, bill_set)
            parts = []
            if inv:
                parts.append(_('INV %s') % inv.name)
            if bill_set:
                parts.append(_('%d bill(s)') % len(bill_set))
            detail = ', '.join(parts)
            if manual:
                detail = _('Manual: %s') % detail

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
