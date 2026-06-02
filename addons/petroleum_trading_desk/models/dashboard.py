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
        }

    @api.model
    def _deal_domain(self, flt, extra=None):
        domain = [
            ('state', '!=', 'cancel'),
            ('date', '>=', flt['date_from']),
            ('date', '<=', flt['date_to']),
        ]
        if flt['partner_id']:
            domain.append(('partner_id', '=', flt['partner_id']))
        if flt['product_id']:
            domain.append(('line_ids.product_id', '=', flt['product_id']))
        if flt['supplier_id']:
            domain.append(('line_ids.supplier_id', '=', flt['supplier_id']))
        if extra:
            domain.extend(extra)
        return domain

    @api.model
    def _line_domain(self, flt):
        domain = [
            ('deal_id.state', '!=', 'cancel'),
            ('deal_id.date', '>=', flt['date_from']),
            ('deal_id.date', '<=', flt['date_to']),
        ]
        if flt['partner_id']:
            domain.append(('deal_id.partner_id', '=', flt['partner_id']))
        if flt['product_id']:
            domain.append(('product_id', '=', flt['product_id']))
        if flt['supplier_id']:
            domain.append(('supplier_id', '=', flt['supplier_id']))
        return domain

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
    def _volume_by_grade(self, lines):
        vol = {grade: 0.0 for grade in GRADE_CODES}
        for line in lines:
            grade = self._grade_code(line.product_id)
            if grade:
                vol[grade] += line.quantity
        return vol

    @api.model
    def _margin_total(self, flt, deals, lines):
        """Margin is the sum of each deal's margin unless a line filter applies."""
        if flt['product_id'] or flt['supplier_id']:
            return sum(lines.mapped('margin'))
        return sum(deals.mapped('margin_total'))

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

        customer_ids = Deal.search([]).mapped('partner_id').ids
        supplier_ids = DealLine.search([]).mapped('supplier_id').ids
        customers = Partner.search(
            [('id', 'in', customer_ids)], order='name') if customer_ids else Partner
        suppliers = Partner.search(
            [('id', 'in', supplier_ids)], order='name') if supplier_ids else Partner

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
        }

    @api.model
    def get_dashboard_data(self, filters=None):
        flt = self._parse_filters(filters)
        Deal = self.env['petroleum.deal']
        DealLine = self.env['petroleum.deal.line']
        today = fields.Date.context_today(self)
        currency = self.env.company.currency_id
        symbol = currency.symbol or ''

        def money(value, dp=0):
            return f"{symbol} {value:,.{dp}f}"

        deals = Deal.search(self._deal_domain(flt))
        lines = DealLine.search(self._line_domain(flt))
        vol = self._volume_by_grade(lines)
        total_litres = sum(vol.values())
        margin_total = self._margin_total(flt, deals, lines)
        sell_total = sum(lines.mapped('price_subtotal'))

        kpis = {
            'margin_total': money(margin_total),
            'margin_per_litre': money(
                margin_total / total_litres if total_litres else 0, 2),
            'margin_pct': f"{(margin_total / sell_total * 100) if sell_total else 0:.1f}%",
            'deals_count': len(deals),
            'sell_total': money(sell_total),
            'litres': {
                grade: f"{vol[grade]:,.0f} L" for grade in GRADE_CODES
            },
            'litres_raw': vol,
        }

        queues = {
            'proforma': Deal.search_count([('state', '=', 'proforma')]),
            'confirmed': Deal.search_count([('state', '=', 'confirmed')]),
            'loaded': Deal.search_count([('state', '=', 'loaded')]),
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

        # Margin trend across the filtered date range (cap at 31 points)
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
            day_deals = deals.filtered(lambda d, day=day: d.date == day)
            if flt['product_id'] or flt['supplier_id']:
                day_lines = lines.filtered(
                    lambda l, day=day: l.deal_id.date == day)
                margin_day = sum(day_lines.mapped('margin'))
            else:
                margin_day = sum(day_deals.mapped('margin_total'))
            trend_labels.append(day.strftime('%d %b'))
            trend_values.append(round(margin_day, 2))

        return {
            'currency': symbol,
            'filters': {
                'date_from': flt['date_from'].isoformat(),
                'date_to': flt['date_to'].isoformat(),
                'product_id': flt['product_id'] or False,
                'partner_id': flt['partner_id'] or False,
                'supplier_id': flt['supplier_id'] or False,
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
            'charts': {
                'margin_trend': {'labels': trend_labels, 'values': trend_values},
                'volume': {
                    'labels': [GRADE_LABELS[g] for g in GRADE_CODES],
                    'values': [round(vol[g], 0) for g in GRADE_CODES],
                    'colors': [GRADE_COLORS[g] for g in GRADE_CODES],
                },
            },
        }

    @api.model
    def action_open_statement_wizard(self):
        return self.env.ref(
            'petroleum_statement_mailer.action_statement_send_wizard'
        ).read()[0]
