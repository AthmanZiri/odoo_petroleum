# Copyright 2024 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models


class OutstandingStatement(models.AbstractModel):
    """Enhanced Outstanding Statement for Odoo 18 compatibility"""

    _inherit = 'report.partner_statement.outstanding_statement'

    def _display_outstanding_lines_sql_q1(self, partners, date_end, account_type):
        partners = tuple(partners)
        truck_sql = self._fuel_truck_sql()
        trip_sql = self._fuel_trip_reference_sql()
        return str(
            self.env.cr.mogrify(
                f"""
            SELECT l.id, m.name AS move_id, l.partner_id, l.date, l.name,
                l.currency_id, l.company_id,
            CASE WHEN l.ref IS NOT NULL
                THEN l.ref
                ELSE m.ref
            END as ref,
            CASE WHEN (l.currency_id is not null AND l.amount_currency > 0.0)
                THEN avg(l.amount_currency)
                ELSE avg(l.debit)
            END as debit,
            CASE WHEN (l.currency_id is not null AND l.amount_currency < 0.0)
                THEN avg(l.amount_currency * (-1))
                ELSE avg(l.credit)
            END as credit,
            CASE WHEN l.balance > 0.0
                THEN l.balance - sum(coalesce(pd.amount, 0.0))
                ELSE l.balance + sum(coalesce(pc.amount, 0.0))
            END AS open_amount,
            CASE WHEN l.balance > 0.0
                THEN l.amount_currency - sum(coalesce(pd.debit_amount_currency, 0.0))
                ELSE l.amount_currency + sum(coalesce(pc.credit_amount_currency, 0.0))
            END AS open_amount_currency,
            CASE WHEN l.date_maturity is null
                THEN l.date
                ELSE l.date_maturity
            END as date_maturity,
            MAX({trip_sql}) as trip_reference,
            MAX({truck_sql}) as truck_number,
            '' as product_references,
            '' as quantity,
            '' as sale_price
            FROM account_move_line l
            JOIN account_account aa ON (aa.id = l.account_id)
            JOIN account_move m ON (l.move_id = m.id)
            LEFT JOIN sale_order so ON (
                %(account_type)s = 'asset_receivable' AND m.invoice_origin = so.name)
            LEFT JOIN trip_sale ts ON (
                %(account_type)s = 'asset_receivable' AND ts.sale_order_id = so.id)
            LEFT JOIN sale_order_line sol ON (
                %(account_type)s = 'asset_receivable' AND sol.order_id = so.id)
            LEFT JOIN product_product pp_sale ON (
                %(account_type)s = 'asset_receivable' AND pp_sale.id = sol.product_id)
            LEFT JOIN product_template pt_sale ON (
                %(account_type)s = 'asset_receivable' AND pt_sale.id = pp_sale.product_tmpl_id)
            LEFT JOIN purchase_order po ON (
                %(account_type)s = 'liability_payable' AND m.invoice_origin = po.name)
            LEFT JOIN purchase_order_line pol ON (
                %(account_type)s = 'liability_payable' AND pol.order_id = po.id)
            LEFT JOIN product_product pp_purchase ON (
                %(account_type)s = 'liability_payable' AND pp_purchase.id = pol.product_id)
            LEFT JOIN product_template pt_purchase ON (
                %(account_type)s = 'liability_payable'
                AND pt_purchase.id = pp_purchase.product_tmpl_id)
            LEFT JOIN trip_management tm ON (
                (%(account_type)s = 'asset_receivable' AND tm.id = ts.trip_id) OR
                (%(account_type)s = 'liability_payable' AND tm.purchase_order_id = po.id))
            LEFT JOIN truck_management truck ON (truck.id = tm.truck_id)
            LEFT JOIN (SELECT pr.*
                FROM account_partial_reconcile pr
                INNER JOIN account_move_line l2
                ON pr.credit_move_id = l2.id
                WHERE l2.date <= %(date_end)s
            ) as pd ON pd.debit_move_id = l.id
            LEFT JOIN (SELECT pr.*
                FROM account_partial_reconcile pr
                INNER JOIN account_move_line l2
                ON pr.debit_move_id = l2.id
                WHERE l2.date <= %(date_end)s
            ) as pc ON pc.credit_move_id = l.id
            WHERE l.partner_id IN %(partners)s
                AND (
                    (pd.id IS NOT NULL AND
                        pd.max_date <= %(date_end)s) OR
                    (pc.id IS NOT NULL AND
                        pc.max_date <= %(date_end)s) OR
                    (pd.id IS NULL AND pc.id IS NULL)
                ) AND l.date <= %(date_end)s AND m.state IN ('posted')
                AND aa.account_type = %(account_type)s
            GROUP BY l.id, l.partner_id, m.id, m.name, l.date, l.date_maturity, l.name,
                CASE WHEN l.ref IS NOT NULL
                    THEN l.ref
                    ELSE m.ref
                END,
                l.currency_id, l.balance, l.amount_currency, l.company_id
            """,
                locals(),
            ),
            "utf-8",
        )

    def _display_outstanding_lines_sql_q2(self, sub):
        return str(
            self.env.cr.mogrify(
                f"""
                SELECT {sub}.partner_id, {sub}.currency_id, {sub}.move_id,
                    {sub}.date, {sub}.date_maturity, {sub}.debit, {sub}.credit,
                    {sub}.name, {sub}.ref, {sub}.company_id,
                    CASE WHEN {sub}.currency_id is not null
                        THEN {sub}.open_amount_currency
                        ELSE {sub}.open_amount
                    END as open_amount, {sub}.id,
                    {sub}.trip_reference, {sub}.truck_number, {sub}.product_references, {sub}.quantity, {sub}.sale_price
                FROM {sub}
                """,
                locals(),
            ),
            "utf-8",
        )

    def _display_outstanding_lines_sql_q3(self, sub, company_id):
        return str(
            self.env.cr.mogrify(
                f"""
            SELECT {sub}.partner_id, {sub}.move_id, {sub}.date,
                {sub}.date_maturity, {sub}.name, {sub}.ref, {sub}.debit,
                {sub}.credit, {sub}.debit-{sub}.credit AS amount,
                COALESCE({sub}.currency_id, c.currency_id) AS currency_id,
                {sub}.open_amount, {sub}.id,
                {sub}.trip_reference, {sub}.truck_number, {sub}.product_references, {sub}.quantity, {sub}.sale_price
            FROM {sub}
            JOIN res_company c ON (c.id = {sub}.company_id)
            WHERE c.id = %(company_id)s AND {sub}.open_amount != 0.0
            """,
                locals(),
            ),
            "utf-8",
        )

    def _get_account_display_lines(
        self, company_id, partner_ids, date_start, date_end, account_type
    ):
        res = dict(map(lambda x: (x, []), partner_ids))
        partners = tuple(partner_ids)
        # pylint: disable=E8103
        self.env.cr.execute(
            """
        WITH Q1 as ({}),
             Q2 AS ({}),
             Q3 AS ({})
        SELECT partner_id, currency_id, move_id, date, date_maturity, debit,
            credit, amount, open_amount, COALESCE(name, '') as name,
            COALESCE(ref, '') as ref, id,
            trip_reference, truck_number, product_references, quantity, sale_price
        FROM Q3
        ORDER BY date, date_maturity, move_id""".format(
                self._display_outstanding_lines_sql_q1(
                    partners, date_end, account_type
                ),
                self._display_outstanding_lines_sql_q2("Q1"),
                self._display_outstanding_lines_sql_q3("Q2", company_id),
            )
        )
        for row in self.env.cr.dictfetchall():
            res[row.pop("partner_id")].append(row)
        return self._enrich_partner_display_lines(res)