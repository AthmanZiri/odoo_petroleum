# Copyright 2024 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, models


class ReportStatementCommon(models.AbstractModel):
    """Enhanced Report Statement Common for Odoo 18 compatibility"""

    _inherit = "statement.common"

    def _apply_customer_ledger_display(self, partner_data, is_activity):
        """Match Excel ledger: positive balance, loadings add, payments subtract."""
        for currency_data in partner_data.get("currencies", {}).values():
            bf = currency_data.get("balance_forward") or 0.0
            running = abs(bf)
            currency_data["balance_forward"] = running
            for line in currency_data.get("lines", []):
                if line.get("reconciled_line"):
                    continue
                running += (line.get("debit") or 0.0) - (line.get("credit") or 0.0)
                line["open_amount"] = running
            if is_activity:
                currency_data["amount_due"] = running
            else:
                currency_data["amount_due"] = running

    @api.model
    def _get_report_values(self, docids, data=None):
        result = super()._get_report_values(docids, data=data)
        is_activity = (data or {}).get("is_activity")
        for partner_data in result.get("data", {}).values():
            self._apply_customer_ledger_display(partner_data, is_activity)
        return result

    def _show_buckets_sql_q1(self, partners, date_end, account_type):
        return str(
            self.env.cr.mogrify(
                """
            SELECT l.partner_id, l.currency_id, l.company_id, l.move_id,
            -(CASE WHEN l.balance > 0.0
                THEN l.balance - sum(coalesce(pd.amount, 0.0))
                ELSE l.balance + sum(coalesce(pc.amount, 0.0))
            END) AS open_due,
            -(CASE WHEN l.balance > 0.0
                THEN l.amount_currency - sum(coalesce(pd.debit_amount_currency, 0.0))
                ELSE l.amount_currency + sum(coalesce(pc.credit_amount_currency, 0.0))
            END) AS open_due_currency,
            CASE WHEN l.date_maturity is null
                THEN l.date
                ELSE l.date_maturity
            END as date_maturity,
            l.date as invoice_date
            FROM account_move_line l
            JOIN account_move m ON (l.move_id = m.id)
            JOIN account_account aa ON (aa.id = l.account_id)
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
                                ) AND l.date <= %(date_end)s
                                  AND m.state IN ('posted')
                                AND aa.account_type = %(account_type)s
            GROUP BY l.partner_id, l.currency_id, l.date, l.date_maturity,
                                l.amount_currency, l.balance, l.move_id,
                                l.company_id, l.id
        """,
                locals(),
            ),
            "utf-8",
        )

    def _show_buckets_sql_q2(self, date_end, minus_30, minus_60, minus_90, minus_120):
        return str(
            self.env.cr.mogrify(
                """
            SELECT partner_id, currency_id, date_maturity, open_due,
                open_due_currency, move_id, company_id, invoice_date,
            CASE
                WHEN %(date_end)s <= invoice_date AND currency_id is null
                    THEN open_due
                WHEN %(date_end)s <= invoice_date AND currency_id is not null
                    THEN open_due_currency
                ELSE 0.0
            END as current,
            CASE
                WHEN %(minus_30)s < invoice_date
                    AND invoice_date < %(date_end)s
                    AND currency_id is null
                THEN open_due
                WHEN %(minus_30)s < invoice_date
                    AND invoice_date < %(date_end)s
                    AND currency_id is not null
                THEN open_due_currency
                ELSE 0.0
            END as b_1_30,
            CASE
                WHEN %(minus_60)s < invoice_date
                    AND invoice_date <= %(minus_30)s
                    AND currency_id is null
                THEN open_due
                WHEN %(minus_60)s < invoice_date
                    AND invoice_date <= %(minus_30)s
                    AND currency_id is not null
                THEN open_due_currency
                ELSE 0.0
            END as b_30_60,
            CASE
                WHEN %(minus_90)s < invoice_date
                    AND invoice_date <= %(minus_60)s
                    AND currency_id is null
                THEN open_due
                WHEN %(minus_90)s < invoice_date
                    AND invoice_date <= %(minus_60)s
                    AND currency_id is not null
                THEN open_due_currency
                ELSE 0.0
            END as b_60_90,
            CASE
                WHEN %(minus_120)s < invoice_date
                    AND invoice_date <= %(minus_90)s
                    AND currency_id is null
                THEN open_due
                WHEN %(minus_120)s < invoice_date
                    AND invoice_date <= %(minus_90)s
                    AND currency_id is not null
                THEN open_due_currency
                ELSE 0.0
            END as b_90_120,
            CASE
                WHEN invoice_date <= %(minus_120)s
                    AND currency_id is null
                THEN open_due
                WHEN invoice_date <= %(minus_120)s
                    AND currency_id is not null
                THEN open_due_currency
                ELSE 0.0
            END as b_over_120
            FROM Q1
            GROUP BY partner_id, currency_id, date_maturity, open_due,
                open_due_currency, move_id, company_id, invoice_date
        """,
                locals(),
            ),
            "utf-8",
        )