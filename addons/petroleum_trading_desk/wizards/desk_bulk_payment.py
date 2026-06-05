from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero


class PetroleumDeskBulkPaymentLine(models.TransientModel):
    _name = 'petroleum.desk.bulk.payment.line'
    _description = 'Bulk payment line'
    _order = 'sequence, invoice_date desc, move_id desc'

    wizard_id = fields.Many2one(
        'petroleum.desk.bulk.payment', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='wizard_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    selected = fields.Boolean(default=True)
    move_id = fields.Many2one('account.move', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='move_id.partner_id', string='Partner')
    invoice_date = fields.Date(related='move_id.invoice_date', string='Date')
    move_name = fields.Char(related='move_id.name', string='Number')
    ref = fields.Char(related='move_id.ref', string='Reference')
    deal_id = fields.Many2one(related='move_id.deal_id', string='Deal')
    amount_total = fields.Monetary(related='move_id.amount_total', string='Total')
    amount_residual = fields.Monetary(related='move_id.amount_residual', string='Due')
    amount_to_pay = fields.Monetary(string='Apply', currency_field='currency_id')
    currency_id = fields.Many2one(related='move_id.currency_id')

    @api.onchange('selected')
    def _onchange_selected(self):
        for line in self:
            if line.selected:
                line.amount_to_pay = line.amount_residual
            else:
                line.amount_to_pay = 0.0

    @api.onchange('amount_to_pay')
    def _onchange_amount_to_pay(self):
        for line in self:
            line.selected = line.amount_to_pay > 0


class PetroleumDeskBulkPayment(models.TransientModel):
    _name = 'petroleum.desk.bulk.payment'
    _description = 'Register Bulk Payments'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    payment_side = fields.Selection(
        [('customer', 'Receive from customers'),
         ('supplier', 'Pay suppliers')],
        string='Payment type', required=True, default='customer')
    partner_id = fields.Many2one(
        'res.partner', string='Partner filter',
        help='Optional: show open documents for this contact only.')
    deal_ids = fields.Many2many(
        'petroleum.deal', string='Deals',
        help='Optional: show only invoices/bills linked to these deals.')
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    payment_date = fields.Date(
        string='Payment date', required=True,
        default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', string='Bank / Cash', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    memo = fields.Char(string='Payment reference')
    amount_paid = fields.Monetary(
        string='Amount paid', currency_field='currency_id',
        help='Total received from the customer or sent to the supplier.')
    group_by_partner = fields.Boolean(
        string='One payment per partner', default=True,
        help='Combine allocations for the same partner into a single bank payment.')
    line_ids = fields.One2many(
        'petroleum.desk.bulk.payment.line', 'wizard_id', string='Open documents')
    selected_count = fields.Integer(compute='_compute_totals')
    selected_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    allocated_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    unallocated_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    result_html = fields.Html(readonly=True)

    @api.depends('line_ids.selected', 'line_ids.amount_residual',
                 'line_ids.amount_to_pay', 'amount_paid')
    def _compute_totals(self):
        for wizard in self:
            selected = wizard.line_ids.filtered('selected')
            wizard.selected_count = len(selected)
            wizard.selected_amount = sum(selected.mapped('amount_residual'))
            wizard.allocated_amount = sum(
                wizard.line_ids.filtered(lambda l: l.amount_to_pay > 0).mapped('amount_to_pay'))
            wizard.unallocated_amount = wizard.amount_paid - wizard.allocated_amount

    @api.model
    def _parse_deal_ids(self, res):
        deal_cmds = res.get('deal_ids') or self.env.context.get('default_deal_ids')
        if not deal_cmds:
            return self.env['petroleum.deal']
        if isinstance(deal_cmds, list) and deal_cmds and isinstance(deal_cmds[0], (list, tuple)):
            if deal_cmds[0][0] == 6:
                return self.env['petroleum.deal'].browse(deal_cmds[0][2])
        return self.env['petroleum.deal'].browse(deal_cmds)

    @api.model
    def _line_vals(self, move, sequence):
        return {
            'move_id': move.id,
            'selected': True,
            'amount_to_pay': move.amount_residual,
            'sequence': sequence,
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company_id = res.get('company_id') or self.env.company.id
        payment_side = res.get('payment_side') or 'customer'
        deals = self._parse_deal_ids(res)
        moves = self._search_open_moves(
            company_id, payment_side,
            partner_id=res.get('partner_id'),
            deal_ids=deals,
            date_from=res.get('date_from'),
            date_to=res.get('date_to'),
        )
        res['line_ids'] = [
            (0, 0, self._line_vals(move, index * 10))
            for index, move in enumerate(moves)
        ]
        if moves and 'amount_paid' in fields_list:
            res['amount_paid'] = sum(moves.mapped('amount_residual'))
        if 'journal_id' in fields_list and not res.get('journal_id'):
            journal = self.env['account.journal'].search([
                ('company_id', '=', company_id),
                ('type', 'in', ('bank', 'cash')),
            ], limit=1)
            if journal:
                res['journal_id'] = journal.id
        return res

    @api.model
    def _search_open_moves(self, company_id, payment_side, partner_id=False,
                           deal_ids=None, date_from=False, date_to=False):
        move_type = 'out_invoice' if payment_side == 'customer' else 'in_invoice'
        domain = [
            ('company_id', '=', company_id),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('move_type', '=', move_type),
        ]
        if partner_id:
            domain.append(('partner_id', 'child_of', partner_id))
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        if date_to:
            domain.append(('invoice_date', '<=', date_to))
        if deal_ids:
            domain.append(('deal_id', 'in', deal_ids.ids))
        return self.env['account.move'].search(domain, order='invoice_date desc, id desc')

    def _sync_lines(self):
        self.ensure_one()
        moves = self._search_open_moves(
            self.company_id.id, self.payment_side,
            partner_id=self.partner_id.id if self.partner_id else False,
            deal_ids=self.deal_ids,
            date_from=self.date_from,
            date_to=self.date_to,
        )
        existing = {line.move_id.id: line for line in self.line_ids}
        commands = []
        sequence = 10
        for move in moves:
            if move.id in existing:
                continue
            commands.append((0, 0, self._line_vals(move, sequence)))
            sequence += 10
        for move_id, line in existing.items():
            if move_id not in moves.ids:
                commands.append((2, line.id))
        if commands:
            self.write({'line_ids': commands})
        return True

    def _rounding(self):
        return self.currency_id.rounding or self.company_id.currency_id.rounding

    def action_refresh_lines(self):
        self._sync_lines()
        return self._reopen()

    def action_select_all(self):
        for line in self.line_ids:
            line.write({'selected': True, 'amount_to_pay': line.amount_residual})
        return self._reopen()

    def action_select_none(self):
        self.line_ids.write({'selected': False, 'amount_to_pay': 0.0})
        return self._reopen()

    def action_fill_amount_paid(self):
        self.ensure_one()
        self.amount_paid = sum(self.line_ids.filtered('selected').mapped('amount_residual'))
        return self._reopen()

    def action_auto_allocate(self):
        """Apply amount_paid to documents in list order (top first)."""
        self.ensure_one()
        if self.amount_paid <= 0:
            raise UserError(_('Enter the amount paid before auto-allocating.'))
        remaining = self.amount_paid
        rounding = self._rounding()
        for line in self.line_ids.sorted('sequence'):
            if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
                line.write({'selected': False, 'amount_to_pay': 0.0})
                continue
            apply = min(line.amount_residual, remaining)
            line.write({'selected': apply > 0, 'amount_to_pay': apply})
            remaining -= apply
        return self._reopen()

    def action_back_to_draft(self):
        self.write({'state': 'draft', 'result_html': False})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _validate_allocations(self):
        self.ensure_one()
        rounding = self._rounding()
        if float_compare(self.amount_paid, 0.0, precision_rounding=rounding) <= 0:
            raise UserError(_('Enter the amount paid.'))
        alloc_lines = self.line_ids.filtered(lambda l: l.amount_to_pay > 0)
        if not alloc_lines:
            raise UserError(_('Allocate the payment to at least one invoice or bill.'))
        if float_compare(self.allocated_amount, self.amount_paid, precision_rounding=rounding) > 0:
            raise UserError(_(
                'Allocated amount (%(alloc)s) exceeds amount paid (%(paid)s).',
                alloc=self.allocated_amount,
                paid=self.amount_paid,
            ))
        for line in alloc_lines:
            if float_compare(line.amount_to_pay, line.amount_residual, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Cannot apply %(apply)s on %(doc)s — only %(due)s is outstanding.',
                    apply=line.amount_to_pay,
                    doc=line.move_name,
                    due=line.amount_residual,
                ))

    def _link_payments_to_deals(self, moves, payments):
        if self.payment_side != 'customer' or not payments:
            return
        for move in moves:
            if move.deal_id:
                move.deal_id.payment_ids = [(4, payment.id) for payment in payments]

    def _payment_method_line(self):
        payment_type = 'inbound' if self.payment_side == 'customer' else 'outbound'
        method_line = self.journal_id._get_available_payment_method_lines(payment_type)[:1]
        if not method_line:
            raise UserError(_('No payment method configured on %s.') % self.journal_id.display_name)
        return method_line

    def _open_payment_lines(self, payment):
        account_types = self.env['account.payment']._get_valid_payment_account_types()
        return payment.move_id.line_ids.filtered(
            lambda l: l.parent_state == 'posted'
            and l.account_id.account_type in account_types
            and not l.reconciled
        )

    def _invoice_payment_lines(self, move):
        account_types = self.env['account.payment']._get_valid_payment_account_types()
        return move.line_ids.filtered(
            lambda l: l.parent_state == 'posted'
            and l.account_id.account_type in account_types
            and not l.reconciled
        )

    def _sequential_reconcile(self, payment, alloc_lines):
        """Reconcile one payment against user allocations in list order."""
        rounding = self._rounding()
        for alloc in alloc_lines.filtered(lambda l: l.amount_to_pay > 0).sorted('sequence'):
            payment_amls = self._open_payment_lines(payment)
            invoice_amls = self._invoice_payment_lines(alloc.move_id)
            if not payment_amls or not invoice_amls:
                continue

            pay_rem = abs(sum(payment_amls.mapped('amount_residual')))
            inv_rem = abs(sum(invoice_amls.mapped('amount_residual')))
            apply = alloc.amount_to_pay

            if float_compare(apply, inv_rem, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Cannot apply %(apply)s on %(doc)s — only %(due)s is outstanding.',
                    apply=apply, doc=alloc.move_name, due=inv_rem,
                ))
            if float_compare(apply, pay_rem, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Cannot apply %(apply)s on %(doc)s — only %(pay)s remains on the payment.',
                    apply=apply, doc=alloc.move_name, pay=pay_rem,
                ))

            is_full_invoice = float_is_zero(apply - inv_rem, precision_rounding=rounding)
            uses_payment_remainder = float_is_zero(apply - pay_rem, precision_rounding=rounding)
            if not is_full_invoice and not uses_payment_remainder:
                raise UserError(_(
                    'Partial payment on %(doc)s must either clear the invoice (%(due)s) '
                    'or use all remaining payment balance (%(pay)s). '
                    'Use Auto-allocate or reorder the lines.',
                    doc=alloc.move_name, due=inv_rem, pay=pay_rem,
                ))

            (payment_amls + invoice_amls).reconcile()

    def _create_partner_payment(self, partner, pay_amount, alloc_lines):
        payment_type = 'inbound' if self.payment_side == 'customer' else 'outbound'
        partner_type = 'customer' if self.payment_side == 'customer' else 'supplier'
        payment = self.env['account.payment'].create({
            'payment_type': payment_type,
            'partner_type': partner_type,
            'partner_id': partner.id,
            'amount': pay_amount,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'memo': self.memo or partner.display_name,
            'payment_method_line_id': self._payment_method_line().id,
        })
        payment.action_post()
        self._sequential_reconcile(payment, alloc_lines)
        return payment

    def _register_single_allocation(self, partner, alloc_line):
        """Fallback: one payment register call for a single partial document."""
        RegisterPayment = self.env['account.payment.register']
        register = RegisterPayment.with_context(
            active_model='account.move',
            active_ids=alloc_line.move_id.ids,
            dont_redirect_to_payments=True,
        ).create({
            'payment_date': self.payment_date,
            'journal_id': self.journal_id.id,
            'amount': alloc_line.amount_to_pay,
            'payment_difference_handling': 'open',
        })
        if self.memo:
            register.communication = self.memo
        return register._create_payments()

    def _can_use_single_payment(self, alloc_lines):
        """True when one bank payment can carry all allocations in order."""
        rounding = self._rounding()
        if not self.group_by_partner:
            return False
        payment_remaining = self.amount_paid
        for alloc in alloc_lines.filtered(lambda l: l.amount_to_pay > 0).sorted('sequence'):
            inv_rem = alloc.amount_residual
            apply = alloc.amount_to_pay
            if float_compare(apply, inv_rem, precision_rounding=rounding) > 0:
                return False
            is_full = float_is_zero(apply - inv_rem, precision_rounding=rounding)
            uses_remainder = float_is_zero(apply - payment_remaining, precision_rounding=rounding)
            if not is_full and not uses_remainder:
                return False
            payment_remaining -= apply
        return True

    def _single_partner_payment(self):
        partners = self.line_ids.filtered(
            lambda l: l.amount_to_pay > 0).mapped('move_id.commercial_partner_id')
        return len(partners) == 1

    def _pay_partner_allocations(self, partner, alloc_lines):
        total_alloc = sum(alloc_lines.mapped('amount_to_pay'))
        pay_amount = self.amount_paid if self._single_partner_payment() else total_alloc

        if self._can_use_single_payment(alloc_lines):
            return self._create_partner_payment(partner, pay_amount, alloc_lines)

        payments = self.env['account.payment']
        for alloc in alloc_lines.filtered(lambda l: l.amount_to_pay > 0).sorted('sequence'):
            payments |= self._register_single_allocation(partner, alloc)
        return payments

    def action_pay(self):
        self.ensure_one()
        if not self.journal_id:
            raise UserError(_('Choose a bank or cash journal.'))
        self._validate_allocations()

        payments = self.env['account.payment']
        rows = []
        errors = []
        alloc_lines = self.line_ids.filtered(lambda l: l.amount_to_pay > 0)

        if self.group_by_partner:
            batches = list(alloc_lines.grouped(
                lambda line: line.move_id.commercial_partner_id
            ).items())
        else:
            batches = [(line.partner_id, line) for line in alloc_lines]

        for partner, lines in batches:
            partner_label = partner.display_name
            try:
                if self.group_by_partner:
                    created = self._pay_partner_allocations(partner, lines)
                    line_set = lines
                else:
                    created = self._register_single_allocation(partner, lines)
                    line_set = lines
                payments |= created
                moves = line_set.mapped('move_id') if self.group_by_partner else lines.move_id
                self._link_payments_to_deals(moves, created)
                iter_lines = line_set.sorted('sequence')[:5] if self.group_by_partner else [lines]
                doc_detail = ', '.join(
                    '%s (%s)' % (l.move_name, l.amount_to_pay) for l in iter_lines
                )
                if self.group_by_partner and len(line_set) > 5:
                    doc_detail += _(' … +%d more') % (len(line_set) - 5)
                pay_names = ', '.join(created.mapped('name'))
                rows.append((partner_label, doc_detail, pay_names, False))
            except UserError as exc:
                errors.append('%s — %s' % (partner_label, exc.args[0]))
                rows.append((partner_label, '', exc.args[0], True))
            except Exception as exc:  # noqa: BLE001
                errors.append('%s — %s' % (partner_label, exc))
                rows.append((partner_label, '', str(exc), True))

        head = (
            '<div><h3>%s</h3>'
            '<p>Created <b>%d</b> payment(s) · Amount paid <b>%s</b> · '
            'Allocated <b>%s</b>'
        ) % (
            _('Payments registered'),
            len(payments),
            self.amount_paid,
            self.allocated_amount,
        )
        if not float_is_zero(self.unallocated_amount, precision_rounding=self._rounding()):
            head += _(' · Unallocated <b>%s</b>') % self.unallocated_amount
        head += '.'
        if errors:
            head += _(' <b>%d</b> partner group(s) failed.') % len(errors)
        head += '</p>'

        trs = []
        for partner, docs, pays, warn in rows[:60]:
            style = 'background:#ffd5d5;' if warn else ''
            trs.append(
                "<tr style='%s'><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (style, partner, docs, pays))
        if len(rows) > 60:
            trs.append("<tr><td colspan='3'>… %d more</td></tr>" % (len(rows) - 60))

        table = (
            "<table class='table table-sm' style='width:100%%'>"
            "<thead><tr><th>Partner</th><th>Applied to</th><th>Payment(s)</th></tr>"
            "</thead><tbody>%s</tbody></table></div>"
        ) % ''.join(trs)

        self.write({'state': 'done', 'result_html': head + table})
        return self._reopen()
