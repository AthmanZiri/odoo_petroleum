# Copyright 2026 Jameel Petroleum
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, models

FUEL_GRADES = ('PMS', 'AGO', 'IK')


class StatementFuelMixin(models.AbstractModel):
    """Shared SQL for trip + petroleum deal + imported invoice line details."""

    _inherit = 'statement.common'

    def _expand_statement_partner_ids(self, partner_ids):
        """Include child contacts so payments on delivery addresses appear on the statement."""
        Partner = self.env['res.partner']
        expanded = set()
        for partner in Partner.browse(partner_ids):
            expanded.update(Partner.search([
                ('commercial_partner_id', '=', partner.commercial_partner_id.id),
            ]).ids)
        return list(expanded)

    def _rollup_statement_partner_data(self, data_by_partner, root_partner_ids):
        """Merge lines from child contacts onto the commercial partner statement."""
        roots = set(root_partner_ids)
        rolled = {pid: [] for pid in root_partner_ids}
        Partner = self.env['res.partner']
        for partner_id, rows in data_by_partner.items():
            commercial = Partner.browse(partner_id).commercial_partner_id.id
            target = commercial if commercial in roots else partner_id
            if target in rolled:
                rolled[target].extend(rows)
        return rolled

    def _rollup_initial_balances(self, balances, root_partner_ids):
        """Sum opening balances from child contacts by currency."""
        roots = set(root_partner_ids)
        totals = {pid: {} for pid in root_partner_ids}
        Partner = self.env['res.partner']
        for partner_id, items in balances.items():
            commercial = Partner.browse(partner_id).commercial_partner_id.id
            target = commercial if commercial in roots else partner_id
            if target not in totals:
                continue
            for item in items:
                currency_id = item['currency_id']
                totals[target][currency_id] = (
                    totals[target].get(currency_id, 0.0) + item['balance']
                )
        return {
            pid: [
                {'currency_id': currency_id, 'balance': balance}
                for currency_id, balance in currency_map.items()
            ]
            for pid, currency_map in totals.items()
        }

    def _has_deal_link(self):
        """True when petroleum_trading_desk linked deal_id is available."""
        move_model = self.env['account.move']
        return (
            'deal_id' in move_model._fields
            and 'petroleum.deal' in self.env
        )

    def _fuel_extra_joins(self):
        """Product/deal data is loaded in Python to avoid row duplication in SQL."""
        return ''

    def _statement_move_debit_sql(self):
        """Sum receivable/payable debit once per move (joins must not duplicate rows)."""
        return """
            (SELECT COALESCE(SUM(
                CASE WHEN (l2.currency_id IS NOT NULL AND l2.amount_currency > 0.0)
                    THEN l2.amount_currency
                    ELSE l2.debit
                END
            ), 0)
            FROM account_move_line l2
            JOIN account_account aa2 ON (aa2.id = l2.account_id)
            WHERE l2.move_id = m.id
              AND l2.partner_id = l.partner_id
              AND aa2.account_type = %(account_type)s)
        """

    def _statement_move_credit_sql(self):
        return """
            (SELECT COALESCE(SUM(
                CASE WHEN (l2.currency_id IS NOT NULL AND l2.amount_currency < 0.0)
                    THEN l2.amount_currency * (-1)
                    ELSE l2.credit
                END
            ), 0)
            FROM account_move_line l2
            JOIN account_account aa2 ON (aa2.id = l2.account_id)
            WHERE l2.move_id = m.id
              AND l2.partner_id = l.partner_id
              AND aa2.account_type = %(account_type)s)
        """

    def _fuel_deal_truck_subquery(self):
        if not self._has_deal_link():
            return "''"
        return """
            (SELECT NULLIF(t.name, '')
             FROM petroleum_deal pd
             JOIN truck_management t ON (t.id = pd.truck_id)
             WHERE pd.id = m.deal_id
             LIMIT 1)
        """

    def _fuel_deal_name_subquery(self):
        if not self._has_deal_link():
            return "''"
        return """
            (SELECT NULLIF(pd.name, '')
             FROM petroleum_deal pd
             WHERE pd.id = m.deal_id
             LIMIT 1)
        """

    def _fuel_truck_sql(self):
        deal_truck = self._fuel_deal_truck_subquery()
        return f"""
            COALESCE(
                NULLIF(truck.name, ''),
                {deal_truck},
                (SELECT t.name
                 FROM truck_management t
                 WHERE length(replace(t.name, ' ', '')) >= 5
                   AND position(
                       upper(replace(t.name, ' ', '')) IN
                       upper(replace(concat(
                           coalesce(m.ref, ''),
                           coalesce(m.narration, ''),
                           coalesce(l.name, ''),
                           coalesce(l.ref, '')
                       ), ' ', ''))) > 0
                 ORDER BY length(t.name) DESC
                 LIMIT 1),
                ''
            )
        """

    def _fuel_trip_reference_sql(self):
        deal_name = self._fuel_deal_name_subquery()
        return f"""
            COALESCE(NULLIF(tm.name, ''), {deal_name}, '')
        """

    def _fuel_product_sql(self, account_type):
        trip_sale = (
            "COALESCE(string_agg(DISTINCT "
            "COALESCE(pt_sale.default_code, ''), ', '), '')"
        )
        trip_purchase = (
            "COALESCE(string_agg(DISTINCT "
            "COALESCE(pt_purchase.default_code, ''), ', '), '')"
        )
        deal_prod = (
            "COALESCE(string_agg(DISTINCT "
            "COALESCE(pt_deal.default_code, ''), ', '), '')"
            if self._has_deal_link()
            else "''"
        )
        inv_prod = (
            "COALESCE(string_agg(DISTINCT "
            "COALESCE(pt_inv.default_code, ''), ', '), '')"
        )
        if account_type == 'asset_receivable':
            return f"""
                COALESCE(
                    NULLIF({trip_sale}, ''),
                    NULLIF({deal_prod}, ''),
                    NULLIF({inv_prod}, ''),
                    ''
                )
            """
        return f"""
            COALESCE(
                NULLIF({trip_purchase}, ''),
                NULLIF({deal_prod}, ''),
                NULLIF({inv_prod}, ''),
                ''
            )
        """

    def _fuel_quantity_sql(self, account_type):
        trip_sale = (
            "COALESCE(string_agg(DISTINCT sol.product_uom_qty::text, ', '), '')"
        )
        trip_purchase = (
            "COALESCE(string_agg(DISTINCT pol.product_qty::text, ', '), '')"
        )
        deal_qty = (
            "COALESCE(string_agg(DISTINCT pdl.quantity::text, ', '), '')"
            if self._has_deal_link()
            else "''"
        )
        inv_qty = (
            "COALESCE(string_agg(DISTINCT aml_prod.quantity::text, ', '), '')"
        )
        if account_type == 'asset_receivable':
            return f"""
                COALESCE(
                    NULLIF({trip_sale}, ''),
                    NULLIF({deal_qty}, ''),
                    NULLIF({inv_qty}, ''),
                    ''
                )
            """
        return f"""
            COALESCE(
                NULLIF({trip_purchase}, ''),
                NULLIF({deal_qty}, ''),
                NULLIF({inv_qty}, ''),
                ''
            )
        """

    def _fuel_rate_sql(self, account_type):
        trip_sale = (
            "COALESCE(string_agg(DISTINCT sol.price_unit::text, ', '), '')"
        )
        trip_purchase = (
            "COALESCE(string_agg(DISTINCT pol.price_unit::text, ', '), '')"
        )
        deal_sell = (
            "COALESCE(string_agg(DISTINCT pdl.sell_price::text, ', '), '')"
            if self._has_deal_link()
            else "''"
        )
        deal_buy = (
            "COALESCE(string_agg(DISTINCT pdl.buy_price::text, ', '), '')"
            if self._has_deal_link()
            else "''"
        )
        inv_rate = (
            "COALESCE(string_agg(DISTINCT aml_prod.price_unit::text, ', '), '')"
        )
        if account_type == 'asset_receivable':
            return f"""
                COALESCE(
                    NULLIF({trip_sale}, ''),
                    NULLIF({deal_sell}, ''),
                    NULLIF({inv_rate}, ''),
                    ''
                )
            """
        return f"""
            COALESCE(
                NULLIF({trip_purchase}, ''),
                NULLIF({deal_buy}, ''),
                NULLIF({inv_rate}, ''),
                ''
            )
        """

    # --- Wide product columns (PMS / AGO / IK) + payment labelling ---

    def _empty_grade_columns(self):
        cols = {}
        for grade in FUEL_GRADES:
            key = grade.lower()
            cols[f'{key}_qty'] = ''
            cols[f'{key}_price'] = ''
        return cols

    def _normalize_grade_code(self, code):
        code = (code or '').upper().strip()
        if code in FUEL_GRADES:
            return code
        for grade in FUEL_GRADES:
            if code.startswith(grade):
                return grade
        return None

    def _format_fuel_qty(self, value):
        if value in (None, ''):
            return ''
        return f'{float(value):,.2f}'

    def _format_fuel_price(self, value):
        if value in (None, ''):
            return ''
        return f'{float(value):,.1f}'

    def _get_move_cached(self, move_name, move_cache):
        if not move_name:
            return self.env['account.move']
        if move_name not in move_cache:
            move_cache[move_name] = self.env['account.move'].search(
                [('name', '=', move_name)], limit=1
            )
        return move_cache[move_name]

    def _fuel_wide_from_move(self, line, move_cache):
        cols = self._empty_grade_columns()
        move = self._get_move_cached(line.get('move_id'), move_cache)
        if not move:
            return cols

        for aml in move.invoice_line_ids.filtered(
            lambda aml: aml.product_id
            and (not aml.display_type or aml.display_type == 'product')
        ).sorted('sequence'):
            grade = self._normalize_grade_code(aml.product_id.default_code)
            if grade:
                key = grade.lower()
                cols[f'{key}_qty'] = self._format_fuel_qty(aml.quantity)
                cols[f'{key}_price'] = self._format_fuel_price(aml.price_unit)

        if any(cols[f'{g.lower()}_qty'] for g in FUEL_GRADES):
            return cols

        if self._has_deal_link() and move.deal_id:
            for pdl in move.deal_id.line_ids:
                grade = self._normalize_grade_code(pdl.product_id.default_code)
                if not grade:
                    continue
                key = grade.lower()
                price = pdl.sell_price or pdl.buy_price
                cols[f'{key}_qty'] = self._format_fuel_qty(pdl.quantity)
                cols[f'{key}_price'] = self._format_fuel_price(price)
        return cols

    def _fuel_wide_from_sql_fields(self, line):
        cols = self._empty_grade_columns()
        products = [
            p.strip()
            for p in str(
                line.get('product_names') or line.get('product_references') or ''
            ).split(',')
            if p.strip()
        ]
        quantities = [
            q.strip() for q in str(line.get('quantity') or '').split(',') if q.strip()
        ]
        rates = [
            r.strip() for r in str(line.get('sale_price') or '').split(',') if r.strip()
        ]
        for index, product in enumerate(products):
            grade = self._normalize_grade_code(product)
            if not grade:
                continue
            key = grade.lower()
            qty = quantities[index] if index < len(quantities) else ''
            rate = rates[index] if index < len(rates) else ''
            cols[f'{key}_qty'] = self._format_fuel_qty(qty) if qty else ''
            cols[f'{key}_price'] = self._format_fuel_price(rate) if rate else ''
        return cols

    def _is_payment_line(self, line, move_cache):
        ref = (line.get('ref') or '').upper()
        if 'PAYMENT' in ref:
            return True
        if line.get('name') in ('/', ''):
            move = self._get_move_cached(line.get('move_id'), move_cache)
            if move and move.journal_id.type in ('bank', 'cash'):
                return bool(line.get('credit'))
            return bool(line.get('credit')) and not line.get('debit')
        move = self._get_move_cached(line.get('move_id'), move_cache)
        if move and move.journal_id.type in ('bank', 'cash'):
            return bool(line.get('credit'))
        if move and getattr(move, 'origin_payment_id', False) and bool(line.get('credit')):
            return True
        return False

    def _payment_bank_label(self, line, move_cache):
        for source in (line.get('truck_number'), line.get('ref'), line.get('name')):
            if not source or source == '/':
                continue
            text = str(source).strip()
            upper = text.upper()
            if upper.startswith('PAYMENT'):
                bank = text[7:].strip(' -:')
                if bank:
                    return bank
            elif upper != 'PAYMENT':
                return text

        move = self._get_move_cached(line.get('move_id'), move_cache)
        if move:
            for source in (move.ref, move.name):
                if not source:
                    continue
                text = str(source).strip()
                upper = text.upper()
                if upper.startswith('PAYMENT'):
                    bank = text[7:].strip(' -:')
                    if bank:
                        return bank
            journal = move.journal_id
            if journal.type in ('bank', 'cash'):
                name = journal.name or ''
                for suffix in (' Bank', ' bank', ' BANK'):
                    if name.endswith(suffix):
                        name = name[: -len(suffix)]
                return name.strip()
        return ''

    def _enrich_payment_line(self, line, move_cache):
        bank = self._payment_bank_label(line, move_cache)
        line['ref'] = _('Payment - %s', bank) if bank else _('Payment')
        line['name'] = '/'
        line['truck_number'] = ''
        line.update(self._empty_grade_columns())
        return line

    def _enrich_statement_line(self, line, move_cache):
        line.update(self._empty_grade_columns())

        if self._is_payment_line(line, move_cache):
            return self._enrich_payment_line(line, move_cache)

        wide = self._fuel_wide_from_move(line, move_cache)
        if not any(wide[f'{g.lower()}_qty'] for g in FUEL_GRADES):
            wide = self._fuel_wide_from_sql_fields(line)
        line.update(wide)

        move = self._get_move_cached(line.get('move_id'), move_cache)
        if move and getattr(move, 'petro_price_adjustment', False):
            kind = (
                _('Customer price adjustment')
                if move.petro_price_adjustment == 'customer_sell'
                else _('Supplier price adjustment')
            )
            line['ref'] = '%s — %s' % (kind, move.ref or move.name)

        truck = (line.get('truck_number') or '').strip()
        if truck and truck.upper().startswith('PAYMENT'):
            line['truck_number'] = ''
        return line

    def _enrich_partner_display_lines(self, lines_by_partner):
        move_cache = {}
        for partner_id, lines in lines_by_partner.items():
            lines_by_partner[partner_id] = [
                self._enrich_statement_line(dict(line), move_cache)
                for line in lines
            ]
        return lines_by_partner
