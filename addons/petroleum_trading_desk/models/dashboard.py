import re
from datetime import timedelta

from odoo import api, fields, models, _

GRADE_CODES = ('PMS', 'AGO', 'IK')
GRADE_LABELS = {
    'PMS': 'PMS (Petrol)',
    'AGO': 'AGO (Diesel)',
    'IK': 'IK (Kerosene)',
}
GRADE_COLORS = {
    'PMS': '#e8a33d',
    'AGO': '#017e84',
    'IK': '#a24689',
}
DEAL_STATE_LABELS = {
    'draft': 'Quotation',
    'proforma': 'Proforma',
    'confirmed': 'Confirmed',
    'loaded': 'Loaded',
    'done': 'Settled',
}
DEAL_STATE_COLORS = {
    'draft': '#6c757d',
    'proforma': '#ffc107',
    'confirmed': '#0dcaf0',
    'loaded': '#6610f2',
    'done': '#198754',
}
DEAL_STATE_FILTER_OPTIONS = [
    ('', 'All statuses'),
    ('draft', 'Quotation'),
    ('proforma', 'Proforma'),
    ('confirmed', 'Confirmed'),
    ('loaded', 'Loaded'),
    ('done', 'Settled'),
]
_SKIP_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


class DeskDashboard(models.TransientModel):
    _name = 'petroleum.desk.dashboard'
    _description = 'Trading Desk Overview'

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------
    @api.model
    def _default_dates(self):
        today = fields.Date.context_today(self)
        return {
            'date_from': today.replace(day=1).isoformat(),
            'date_to': today.isoformat(),
        }

    @api.model
    def _parse_filters(self, filters=None):
        filters = filters or {}
        today = fields.Date.context_today(self)
        defaults = self._default_dates()
        date_from = fields.Date.to_date(filters.get('date_from')) or fields.Date.to_date(
            defaults['date_from'])
        date_to = fields.Date.to_date(filters.get('date_to')) or fields.Date.to_date(
            defaults['date_to'])
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return {
            'date_from': date_from,
            'date_to': date_to,
            'product_id': int(filters['product_id']) if filters.get('product_id') else False,
            'partner_id': int(filters['partner_id']) if filters.get('partner_id') else False,
            'supplier_id': int(filters['supplier_id']) if filters.get('supplier_id') else False,
            'deal_state': filters.get('deal_state') or '',
        }

    @api.model
    def _deal_domain(self, flt, extra=None):
        domain = [
            ('state', '!=', 'cancel'),
            ('date', '>=', flt['date_from']),
            ('date', '<=', flt['date_to']),
        ]
        if flt.get('deal_state'):
            domain.append(('state', '=', flt['deal_state']))
        if flt['partner_id']:
            domain.append(('partner_id', '=', flt['partner_id']))
        if flt['product_id']:
            domain.append(('line_ids.product_id', '=', flt['product_id']))
        if flt['supplier_id']:
            domain.append(('line_ids.supplier_id', '=', flt['supplier_id']))
        if extra:
            domain.extend(extra)
        return domain

    @staticmethod
    def _invoice_effective_date(invoice):
        return invoice.invoice_date or invoice.date

    @api.model
    def _invoice_in_period(self, invoice, flt):
        eff = self._invoice_effective_date(invoice)
        return bool(eff and flt['date_from'] <= eff <= flt['date_to'])

    @api.model
    def _is_invoice_product_line(self, line):
        return bool(line.product_id and line.display_type not in _SKIP_LINE_DISPLAY)

    @staticmethod
    def _grade_code(product):
        code = (product.default_code or '').upper()
        if code in GRADE_CODES:
            return code
        name = (product.display_name or '').upper()
        for grade in GRADE_CODES:
            if grade in name:
                return grade
        return None

    @api.model
    def _volume_by_grade_from_lines(self, move_lines):
        vol = {grade: 0.0 for grade in GRADE_CODES}
        for line in move_lines:
            if not self._is_invoice_product_line(line):
                continue
            grade = self._grade_code(line.product_id)
            if grade:
                vol[grade] += line.quantity
        return vol

    @api.model
    def _invoice_deal(self, invoice):
        if invoice.deal_id:
            return invoice.deal_id
        orders = invoice.invoice_line_ids.sale_line_ids.order_id
        if orders:
            deal = self.env['petroleum.deal'].search(
                [('sale_order_id', 'in', orders.ids)], limit=1)
            if deal:
                return deal
        origin = (invoice.invoice_origin or invoice.ref or '').strip()
        if origin:
            deal = self.env['petroleum.deal'].search([('name', '=', origin)], limit=1)
            if deal:
                return deal
        return self.env['petroleum.deal']

    @api.model
    def _posted_customer_invoices(self, moves):
        return moves.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted')

    @api.model
    def _get_dashboard_invoices(self, flt):
        """Collect posted customer invoices from trading deals and petroleum imports."""
        Move = self.env['account.move']
        Deal = self.env['petroleum.deal']

        Deal.backfill_move_deal_links()

        invoice_ids = set()

        deal_domain = [
            ('state', 'not in', ('cancel',)),
            '|', ('sale_order_id', '!=', False), ('ledger_move_ids', '!=', False),
        ]
        for deal in Deal.search(deal_domain):
            for inv in self._posted_customer_invoices(deal.invoice_ids):
                if self._invoice_in_period(inv, flt):
                    invoice_ids.add(inv.id)

        linked = Move.search([
            ('deal_id', '!=', False),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ])
        for inv in linked:
            if self._invoice_in_period(inv, flt):
                invoice_ids.add(inv.id)

        if 'petro_import_batch' in Move._fields:
            imported = Move.search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('petro_import_batch', '!=', False),
                ('deal_id', '=', False),
            ])
            for inv in imported:
                if self._invoice_in_period(inv, flt):
                    invoice_ids.add(inv.id)

        invoices = Move.browse(list(invoice_ids))

        if flt['partner_id']:
            invoices = invoices.filtered(
                lambda inv: inv.partner_id.id == flt['partner_id'])

        if flt['product_id']:
            pid = flt['product_id']
            invoices = invoices.filtered(
                lambda inv: any(
                    self._is_invoice_product_line(l) and l.product_id.id == pid
                    for l in inv.invoice_line_ids))

        if flt['supplier_id']:
            sid = flt['supplier_id']
            matched = Move.browse()
            for inv in invoices:
                deal = self._invoice_deal(inv)
                if deal and deal.line_ids.filtered(lambda l: l.supplier_id.id == sid):
                    matched |= inv
            invoices = matched

        return invoices

    @api.model
    def _filter_invoice_lines(self, invoice, flt):
        lines = invoice.invoice_line_ids.filtered(
            lambda l: self._is_invoice_product_line(l))
        if flt['product_id']:
            lines = lines.filtered(lambda l: l.product_id.id == flt['product_id'])
        if flt['supplier_id']:
            deal = self._invoice_deal(invoice)
            if not deal:
                return lines.browse()
            supplier_products = deal.line_ids.filtered(
                lambda l, sid=flt['supplier_id']: l.supplier_id.id == sid
            ).mapped('product_id')
            lines = lines.filtered(lambda l: l.product_id in supplier_products)
        return lines

    @api.model
    def _filter_deal_lines(self, deal, flt):
        lines = deal.line_ids
        if flt['product_id']:
            lines = lines.filtered(lambda l: l.product_id.id == flt['product_id'])
        if flt['supplier_id']:
            lines = lines.filtered(lambda l: l.supplier_id.id == flt['supplier_id'])
        return lines

    @api.model
    def _deal_buy_total(self, deal):
        bills = deal.bill_ids.filtered(lambda m: m.state == 'posted')
        if bills:
            return sum(bills.mapped('amount_untaxed'))
        return sum(deal.line_ids.mapped('cost_subtotal'))

    @api.model
    def _get_imported_vendor_bills(self, flt):
        """Posted supplier bills created by petroleum ledger import."""
        if 'petro_import_batch' not in self.env['account.move']._fields:
            return self.env['account.move']
        bills = self.env['account.move'].search([
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
            ('petro_import_batch', '!=', False),
        ])
        bills = bills.filtered(lambda m: self._invoice_in_period(m, flt))
        if flt['supplier_id']:
            bills = bills.filtered(
                lambda m, sid=flt['supplier_id']: m.partner_id.id == sid)
        if flt['product_id']:
            pid = flt['product_id']
            bills = bills.filtered(
                lambda m, pid=pid: any(
                    self._is_invoice_product_line(l) and l.product_id.id == pid
                    for l in m.invoice_line_ids))
        return bills

    @staticmethod
    def _plain_text(value):
        if not value:
            return ''
        return re.sub(r'<[^>]+>', '', str(value)).strip()

    @api.model
    def _invoice_truck_token(self, invoice):
        """Truck plate from imported invoice ref / narration."""
        ref = self._plain_text(invoice.ref)
        if ref and not ref.upper().startswith('INV/'):
            if ' - INV/' in ref:
                return ref.split(' - INV/')[0].strip()
            return ref
        name = self._plain_text(invoice.name)
        if ' - INV/' in name:
            return name.split(' - INV/')[0].strip()
        narr = self._plain_text(invoice.narration)
        if narr:
            return narr.split('\n')[0].strip()
        return ''

    @api.model
    def _bills_for_import_truck(self, truck, eff_date):
        if not truck or not eff_date:
            return self.env['account.move']
        truck_key = truck.upper().replace(' ', '')
        day_bills = self.env['account.move'].search([
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
            ('petro_import_batch', '!=', False),
            ('invoice_date', '=', eff_date),
        ])
        matched = self.env['account.move']
        for bill in day_bills:
            blob = ' '.join(filter(None, [
                self._plain_text(bill.ref),
                self._plain_text(bill.narration),
                self._plain_text(bill.name),
            ])).upper().replace(' ', '')
            if truck_key and truck_key in blob:
                matched |= bill
        return matched

    @api.model
    def _import_invoice_matched_buy(self, invoice):
        """Buy cost from imported vendor bill lines (same date, truck, product grade)."""
        truck = self._invoice_truck_token(invoice)
        eff = self._invoice_effective_date(invoice)
        bills = self._bills_for_import_truck(truck, eff)
        if not bills:
            return 0.0
        buy = 0.0
        for inv_line in invoice.invoice_line_ids.filtered(
            lambda l: self._is_invoice_product_line(l)
        ):
            grade = self._grade_code(inv_line.product_id)
            if not grade:
                continue
            qty = inv_line.quantity
            for bill in bills:
                for bill_line in bill.invoice_line_ids.filtered(
                    lambda l: self._is_invoice_product_line(l)
                ):
                    if self._grade_code(bill_line.product_id) != grade:
                        continue
                    line_qty = min(qty, bill_line.quantity)
                    buy += bill_line.price_unit * line_qty
                    qty -= line_qty
                    if qty <= 0:
                        break
        return buy

    @api.model
    def _invoice_sell_and_volume(self, invoices, flt):
        all_lines = self.env['account.move.line']
        for invoice in invoices:
            all_lines |= self._filter_invoice_lines(invoice, flt)
        vol = self._volume_by_grade_from_lines(all_lines)
        sell_total = sum(all_lines.mapped('price_subtotal'))
        return sell_total, vol

    @api.model
    def _invoice_margin(self, invoices, flt):
        margin = 0.0
        for invoice in invoices:
            lines = self._filter_invoice_lines(invoice, flt)
            line_margin = sum(lines.mapped('petro_margin'))
            if line_margin:
                margin += line_margin
            else:
                sell = sum(lines.mapped('price_subtotal'))
                buy = self._import_invoice_matched_buy(invoice)
                margin += sell - buy
        return margin

    @api.model
    def _import_invoices_outside_period(self, flt):
        if 'petro_import_batch' not in self.env['account.move']._fields:
            return 0
        imported = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('petro_import_batch', '!=', False),
        ])
        return len(imported.filtered(lambda m: not self._invoice_in_period(m, flt)))

    @api.model
    def _margin_by_invoice_date(self, invoices, flt, day):
        day_invoices = invoices.filtered(
            lambda inv, day=day: self._invoice_effective_date(inv) == day)
        if not day_invoices:
            return 0.0
        return self._invoice_margin(day_invoices, flt)

    @api.model
    def _deals_pipeline(self, flt):
        Deal = self.env['petroleum.deal']
        states = ('draft', 'proforma', 'confirmed', 'loaded', 'done')
        deals = Deal.search(self._deal_domain(flt))
        counts, margins = [], []
        for state in states:
            state_deals = deals.filtered(lambda d, state=state: d.state == state)
            counts.append(len(state_deals))
            margins.append(round(sum(state_deals.mapped('margin_total')), 2))
        return {
            'labels': [DEAL_STATE_LABELS[s] for s in states],
            'counts': counts,
            'margins': margins,
            'colors': [DEAL_STATE_COLORS[s] for s in states],
            'total_count': len(deals),
            'total_margin': round(sum(deals.mapped('margin_total')), 2),
        }

    # ------------------------------------------------------------------
    # Data feed for the OWL dashboard
    # ------------------------------------------------------------------
    @api.model
    def get_filter_options(self):
        Deal = self.env['petroleum.deal']
        DealLine = self.env['petroleum.deal.line']
        Product = self.env['product.product']
        Partner = self.env['res.partner']

        products = Product.search(
            [('fuel_ok', '=', True), ('default_code', 'in', list(GRADE_CODES))],
            order='default_code')
        if len(products) < len(GRADE_CODES):
            products = Product.search([('fuel_ok', '=', True)], order='name')

        customer_ids = set(Deal.search([]).mapped('partner_id').ids)
        supplier_ids = set(DealLine.search([]).mapped('supplier_id').ids)
        Move = self.env['account.move']
        if 'petro_import_batch' in Move._fields:
            imported_inv = Move.search([
                ('move_type', '=', 'out_invoice'),
                ('petro_import_batch', '!=', False),
            ])
            customer_ids.update(imported_inv.mapped('partner_id').ids)
            imported_bill = Move.search([
                ('move_type', '=', 'in_invoice'),
                ('petro_import_batch', '!=', False),
            ])
            supplier_ids.update(imported_bill.mapped('partner_id').ids)
        customers = Partner.search(
            [('id', 'in', list(customer_ids))], order='name') if customer_ids else Partner
        suppliers = Partner.search(
            [('id', 'in', list(supplier_ids))], order='name') if supplier_ids else Partner

        def partner_opts(records):
            return [{'id': p.id, 'name': p.display_name} for p in records[:200]]

        return {
            'defaults': self._default_dates(),
            'products': [
                {'id': p.id, 'name': GRADE_LABELS.get(p.default_code, p.display_name)}
                for p in products
            ],
            'customers': partner_opts(customers),
            'suppliers': partner_opts(suppliers),
            'deal_states': [
                {'value': value, 'label': label}
                for value, label in DEAL_STATE_FILTER_OPTIONS
            ],
        }

    @api.model
    def _position_summary(self, flt):
        """Bulk position totals for the reference day in the filter window."""
        today = fields.Date.context_today(self)
        if flt['date_from'] <= today <= flt['date_to']:
            pos_date = today
        else:
            pos_date = flt['date_to']
        domain = [('date', '=', pos_date)]
        if flt['product_id']:
            domain.append(('product_id', '=', flt['product_id']))
        if flt['supplier_id']:
            domain.append(('supplier_id', '=', flt['supplier_id']))
        lines = self.env['petroleum.daily.position.line'].search(domain)
        vol = {grade: {'total': 0.0, 'sold': 0.0, 'remaining': 0.0} for grade in GRADE_CODES}
        totals = {'opening': 0.0, 'bought': 0.0, 'total': 0.0,
                  'sold': 0.0, 'remaining': 0.0}
        for line in lines:
            totals['opening'] += line.qty_opening
            totals['bought'] += line.qty_bought
            totals['total'] += line.qty_total
            totals['sold'] += line.qty_sold
            totals['remaining'] += line.qty_remaining
            grade = self._grade_code(line.product_id)
            if grade:
                vol[grade]['total'] += line.qty_total
                vol[grade]['sold'] += line.qty_sold
                vol[grade]['remaining'] += line.qty_remaining
        return {
            'date': pos_date.isoformat(),
            'line_count': len(lines),
            'totals': totals,
            'by_grade': vol,
        }

    @api.model
    def get_dashboard_data(self, filters=None):
        flt = self._parse_filters(filters)
        Deal = self.env['petroleum.deal']
        today = fields.Date.context_today(self)
        currency = self.env.company.currency_id
        symbol = currency.symbol or ''

        def money(value, dp=0):
            return f"{symbol} {value:,.{dp}f}"

        invoices = self._get_dashboard_invoices(flt)
        import_invoices = invoices.filtered(
            lambda m: getattr(m, 'petro_import_batch', False) and not m.deal_id)
        deal_invoices = invoices - import_invoices
        import_bills = self._get_imported_vendor_bills(flt)
        sell_total, vol = self._invoice_sell_and_volume(invoices, flt)
        total_litres = sum(vol.values())
        margin_total = self._invoice_margin(invoices, flt)
        deals_pipeline = self._deals_pipeline(flt)
        imports_outside = self._import_invoices_outside_period(flt)

        kpis = {
            'margin_total': money(margin_total),
            'margin_per_litre': money(
                margin_total / total_litres if total_litres else 0, 2),
            'margin_pct': f"{(margin_total / sell_total * 100) if sell_total else 0:.1f}%",
            'invoices_count': len(invoices),
            'import_invoices_count': len(import_invoices),
            'deal_invoices_count': len(deal_invoices),
            'import_bills_count': len(import_bills),
            'invoice_ids': invoices.ids,
            'deals_count': deals_pipeline['total_count'],
            'imports_outside_period': imports_outside,
            'sell_total': money(sell_total),
            'litres': {
                grade: f"{vol[grade]:,.0f} L" for grade in GRADE_CODES
            },
            'litres_raw': vol,
        }

        queue_flt = dict(flt, deal_state='')

        def _queue_count(state):
            extra = [('state', '=', state)]
            if flt.get('deal_state') and flt['deal_state'] != state:
                return 0
            return Deal.search_count(self._deal_domain(queue_flt, extra))

        queues = {
            'proforma': _queue_count('proforma'),
            'confirmed': _queue_count('confirmed'),
            'loaded': _queue_count('loaded'),
        }

        customers = self.env['res.partner'].search(
            [('customer_rank', '>', 0), ('parent_id', '=', False)])
        debtor_recs = customers.filtered(lambda p: p.credit > 0).sorted(
            key=lambda p: p.credit, reverse=True)[:8]
        debtors = [{
            'id': p.id,
            'name': p.display_name,
            'amount': money(p.credit),
        } for p in debtor_recs]
        total_debtors = sum(p.credit for p in customers if p.credit > 0)

        aml = self.env['account.move.line'].search([
            ('partner_id', 'in', customers.ids),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('amount_residual', '>', 0),
        ])
        buckets = {'current': 0.0, 'b1': 0.0, 'b2': 0.0, 'b3': 0.0}
        for line in aml:
            due = line.date_maturity or line.date
            days = (today - due).days
            residual = line.amount_residual
            if days <= 0:
                buckets['current'] += residual
            elif days <= 30:
                buckets['b1'] += residual
            elif days <= 60:
                buckets['b2'] += residual
            else:
                buckets['b3'] += residual
        aging = [
            {'label': 'Not due', 'amount': money(buckets['current']),
             'raw': round(buckets['current'], 2), 'danger': False},
            {'label': '1-30 days', 'amount': money(buckets['b1']),
             'raw': round(buckets['b1'], 2), 'danger': False},
            {'label': '31-60 days', 'amount': money(buckets['b2']),
             'raw': round(buckets['b2'], 2), 'danger': True},
            {'label': '60+ days', 'amount': money(buckets['b3']),
             'raw': round(buckets['b3'], 2), 'danger': True},
        ]

        span = (flt['date_to'] - flt['date_from']).days + 1
        if span <= 31:
            trend_days = [
                flt['date_from'] + timedelta(days=i) for i in range(span)]
        else:
            trend_days = [
                flt['date_from'] + timedelta(
                    days=round(i * (span - 1) / 30))
                for i in range(31)
            ]
        trend_labels, trend_values = [], []
        for day in trend_days:
            margin_day = self._margin_by_invoice_date(invoices, flt, day)
            trend_labels.append(day.strftime('%d %b'))
            trend_values.append(round(margin_day, 2))

        position = self._position_summary(flt)
        pos = position['totals']

        return {
            'currency': symbol,
            'filters': {
                'date_from': flt['date_from'].isoformat(),
                'date_to': flt['date_to'].isoformat(),
                'product_id': flt['product_id'] or False,
                'partner_id': flt['partner_id'] or False,
                'supplier_id': flt['supplier_id'] or False,
                'deal_state': flt.get('deal_state') or False,
            },
            'period_label': '%s – %s' % (
                flt['date_from'].strftime('%d %b %Y'),
                flt['date_to'].strftime('%d %b %Y'),
            ),
            'kpis': kpis,
            'queues': queues,
            'debtors': debtors,
            'total_debtors': money(total_debtors),
            'aging': aging,
            'position': {
                'date': position['date'],
                'line_count': position['line_count'],
                'opening': f"{pos['opening']:,.0f} L",
                'bought': f"{pos['bought']:,.0f} L",
                'total': f"{pos['total']:,.0f} L",
                'sold': f"{pos['sold']:,.0f} L",
                'remaining': f"{pos['remaining']:,.0f} L",
                'remaining_raw': pos['remaining'],
                'by_grade': {
                    grade: {
                        'total': f"{position['by_grade'][grade]['total']:,.0f} L",
                        'remaining': f"{position['by_grade'][grade]['remaining']:,.0f} L",
                    }
                    for grade in GRADE_CODES
                },
            },
            'charts': {
                'margin_trend': {'labels': trend_labels, 'values': trend_values},
                'volume': {
                    'labels': [GRADE_LABELS[g] for g in GRADE_CODES],
                    'values': [round(vol[g], 0) for g in GRADE_CODES],
                    'colors': [GRADE_COLORS[g] for g in GRADE_CODES],
                },
                'deals_pipeline': deals_pipeline,
            },
        }

    @api.model
    def action_open_statement_wizard(self):
        return self.env.ref(
            'petroleum_statement_mailer.action_statement_send_wizard'
        ).read()[0]
