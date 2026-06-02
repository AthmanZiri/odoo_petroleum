# Copyright 2024 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, models


class ActivityStatement(models.AbstractModel):
    """Enhanced Activity Statement with Trip Information"""

    _inherit = "report.partner_statement.activity_statement"

    def _initial_balance_sql_q1(self, partners, date_start, account_type):
        return str(
            self.env.cr.mogrify(
                """
            SELECT l.partner_id, l.currency_id, l.company_id, l.id,
                -(CASE WHEN l.balance > 0.0
                    THEN l.balance - sum(coalesce(pd.amount, 0.0))
                    ELSE l.balance + sum(coalesce(pc.amount, 0.0))
                END) AS open_amount,
                -(CASE WHEN l.balance > 0.0
                    THEN l.amount_currency - sum(coalesce(
                        pd.debit_amount_currency, 0.0)
                    )
                    ELSE l.amount_currency + sum(coalesce(
                        pc.credit_amount_currency, 0.0)
                    )
                END) AS open_amount_currency
            FROM account_move_line l
            JOIN account_account aa ON (aa.id = l.account_id)
            JOIN account_move m ON (l.move_id = m.id)
            LEFT JOIN (SELECT pr.*
                FROM account_partial_reconcile pr
                INNER JOIN account_move_line l2
                ON pr.credit_move_id = l2.id
                WHERE l2.date < %(date_start)s
            ) as pd ON pd.debit_move_id = l.id
            LEFT JOIN (SELECT pr.*
                FROM account_partial_reconcile pr
                INNER JOIN account_move_line l2
                ON pr.debit_move_id = l2.id
                WHERE l2.date < %(date_start)s
            ) as pc ON pc.credit_move_id = l.id
            WHERE l.partner_id IN %(partners)s
                AND l.date < %(date_start)s
                AND m.state IN ('posted')
                AND aa.account_type = %(account_type)s
                AND (
                    (pd.id IS NOT NULL AND
                        pd.max_date < %(date_start)s) OR
                    (pc.id IS NOT NULL AND
                        pc.max_date < %(date_start)s) OR
                    (pd.id IS NULL AND pc.id IS NULL)
                )
            GROUP BY l.partner_id, l.currency_id, l.company_id, l.balance, l.id
        """,
                locals(),
            ),
            "utf-8",
        )

    def _display_activity_lines_sql_q1(
        self, partners, date_start, date_end, account_type
    ):
        payment_ref = _("Payment")
        return str(
            self.env.cr.mogrify(
                """
            SELECT m.name AS move_id, l.partner_id, l.date,
                array_agg(l.id ORDER BY l.id) as ids,
                CASE WHEN (aj.type IN ('sale', 'purchase'))
                    THEN l.name
                    ELSE '/'
                END as name,
                CASE
                    WHEN (aj.type IN ('sale', 'purchase')) AND l.name IS NOT NULL
                        THEN l.ref
                    WHEN (aj.type in ('bank', 'cash'))
                        THEN %(payment_ref)s
                    ELSE m.ref
                END as case_ref,
                l.currency_id, l.company_id,
                sum(CASE WHEN (l.currency_id is not null AND l.amount_currency > 0.0)
                    THEN l.amount_currency
                    ELSE l.debit
                END) as debit,
                sum(CASE WHEN (l.currency_id is not null AND l.amount_currency < 0.0)
                    THEN l.amount_currency * (-1)
                    ELSE l.credit
                END) as credit,
                CASE WHEN l.date_maturity is null
                    THEN l.date
                    ELSE l.date_maturity
                END as date_maturity,
                COALESCE(tm.name, '') as trip_reference,
                COALESCE(truck.name, '') as truck_number,
                CASE WHEN %(account_type)s = 'asset_receivable'
                    THEN COALESCE(string_agg(DISTINCT COALESCE(pt_sale.default_code, ''), ', '), '')
                    ELSE COALESCE(string_agg(DISTINCT COALESCE(pt_purchase.default_code, ''), ', '), '')
                END as product_names,
                CASE WHEN %(account_type)s = 'asset_receivable'
                    THEN COALESCE(string_agg(DISTINCT sol.product_uom_qty::text, ', '), '')
                    ELSE COALESCE(string_agg(DISTINCT pol.product_qty::text, ', '), '')
                END as quantity,
                CASE WHEN %(account_type)s = 'asset_receivable'
                    THEN COALESCE(string_agg(DISTINCT sol.price_unit::text, ', '), '')
                    ELSE COALESCE(string_agg(DISTINCT pol.price_unit::text, ', '), '')
                END as sale_price
            FROM account_move_line l
            JOIN account_account aa ON (aa.id = l.account_id)
            JOIN account_move m ON (l.move_id = m.id)
            JOIN account_journal aj ON (l.journal_id = aj.id)
            -- Receivables (Customer) joins
            LEFT JOIN sale_order so ON (%(account_type)s = 'asset_receivable' AND m.invoice_origin = so.name)
            LEFT JOIN trip_sale ts ON (%(account_type)s = 'asset_receivable' AND ts.sale_order_id = so.id)
            LEFT JOIN sale_order_line sol ON (%(account_type)s = 'asset_receivable' AND sol.order_id = so.id)
            LEFT JOIN product_product pp_sale ON (%(account_type)s = 'asset_receivable' AND pp_sale.id = sol.product_id)
            LEFT JOIN product_template pt_sale ON (%(account_type)s = 'asset_receivable' AND pt_sale.id = pp_sale.product_tmpl_id)
            -- Payables (Vendor) joins
            LEFT JOIN purchase_order po ON (%(account_type)s = 'liability_payable' AND m.invoice_origin = po.name)
            LEFT JOIN purchase_order_line pol ON (%(account_type)s = 'liability_payable' AND pol.order_id = po.id)
            LEFT JOIN product_product pp_purchase ON (%(account_type)s = 'liability_payable' AND pp_purchase.id = pol.product_id)
            LEFT JOIN product_template pt_purchase ON (%(account_type)s = 'liability_payable' AND pt_purchase.id = pp_purchase.product_tmpl_id)
            -- Common trip joins (works for both receivables and payables)
            LEFT JOIN trip_management tm ON (
                (%(account_type)s = 'asset_receivable' AND tm.id = ts.trip_id) OR
                (%(account_type)s = 'liability_payable' AND tm.purchase_order_id = po.id)
            )
            LEFT JOIN truck_management truck ON (truck.id = tm.truck_id)
            WHERE l.partner_id IN %(partners)s
                AND %(date_start)s <= l.date
                AND l.date <= %(date_end)s
                AND m.state IN ('posted')
                AND aa.account_type = %(account_type)s
            GROUP BY l.partner_id, m.name, l.date, l.date_maturity,
                CASE WHEN (aj.type IN ('sale', 'purchase'))
                    THEN l.name
                    ELSE '/'
                END, case_ref, l.currency_id, l.company_id,
                tm.name, truck.name
        """,
                locals(),
            ),
            "utf-8",
        )

    def _display_activity_lines_sql_q2(self, sub, company_id):
        return str(
            self.env.cr.mogrify(
                f"""
            SELECT {sub}.partner_id, {sub}.move_id, {sub}.date, {sub}.date_maturity,
                {sub}.name, {sub}.case_ref as ref, {sub}.debit, {sub}.credit, {sub}.ids,
                {sub}.debit-{sub}.credit as amount,
                COALESCE({sub}.currency_id, c.currency_id) AS currency_id,
                {sub}.trip_reference, {sub}.truck_number, {sub}.product_names, {sub}.quantity, {sub}.sale_price
            FROM {sub}
            JOIN res_company c ON (c.id = {sub}.company_id)
            WHERE c.id = %(company_id)s
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
        WITH Q1 AS ({}),
             Q2 AS ({})
        SELECT partner_id, move_id, date, date_maturity, ids,
            COALESCE(name, '') as name, COALESCE(ref, '') as ref,
            debit, credit, amount, currency_id,
            trip_reference, truck_number, product_names, quantity, sale_price
        FROM Q2
        ORDER BY date, date_maturity, move_id""".format(
                self._display_activity_lines_sql_q1(
                    partners, date_start, date_end, account_type
                ),
                self._display_activity_lines_sql_q2("Q1", company_id),
            )
        )
        for row in self.env.cr.dictfetchall():
            res[row.pop("partner_id")].append(row)
        return res

    def _display_activity_reconciled_lines_sql_q2(self, sub, date_end):
        return str(
            self.env.cr.mogrify(
                f"""
            SELECT l.id as rel_id, m.name AS move_id, l.partner_id, l.date, l.name,
                l.currency_id, l.company_id, {sub}.id,
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
            -(CASE WHEN l.balance > 0.0
                THEN sum(coalesce(pc.amount, 0.0))
                ELSE -sum(coalesce(pd.amount, 0.0))
            END) AS open_amount,
            -(CASE WHEN l.balance > 0.0
                THEN sum(coalesce(pc.debit_amount_currency, 0.0))
                ELSE -sum(coalesce(pd.credit_amount_currency, 0.0))
            END) AS open_amount_currency,
            CASE WHEN l.date_maturity is null
                THEN l.date
                ELSE l.date_maturity
            END as date_maturity
            FROM {sub}
            LEFT JOIN account_partial_reconcile pd ON (
                pd.debit_move_id = {sub}.id AND pd.max_date <= %(date_end)s)
            LEFT JOIN account_partial_reconcile pc ON (
                pc.credit_move_id = {sub}.id AND pc.max_date <= %(date_end)s)
            LEFT JOIN account_move_line l ON (
                pd.credit_move_id = l.id OR pc.debit_move_id = l.id)
            LEFT JOIN account_move m ON (l.move_id = m.id)
            WHERE l.date <= %(date_end)s AND m.state IN ('posted')
            GROUP BY l.id, l.partner_id, m.name, l.date, l.date_maturity, l.name,
                CASE WHEN l.ref IS NOT NULL
                    THEN l.ref
                    ELSE m.ref
                END, {sub}.id,
                l.currency_id, l.balance, l.amount_currency, l.company_id
        """,
                locals(),
            ),
            "utf-8",
        )