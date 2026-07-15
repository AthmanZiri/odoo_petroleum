# -*- coding: utf-8 -*-
import json
from collections import defaultdict

from odoo import _, fields, models
from odoo.tools import SQL


class AccountBookReportHandler(models.AbstractModel):
    """Shared General-Ledger-based handler for Daily Books (Bank / Cash / Day)."""
    _name = 'account.book.report.handler'
    _inherit = 'account.general.ledger.report.handler'
    _description = 'Daily Book Report Handler'

    _book_journal_types = ()
    _book_total_label = 'Total'

    def _get_book_journal_types(self):
        return self._book_journal_types

    def _get_book_total_label(self):
        return _(self._book_total_label)

    def _get_book_account_ids(self, report, options):
        """Liquidity accounts linked to the currently selected book journals."""
        journal_types = self._get_book_journal_types()
        if not journal_types:
            return []

        selected_journal_ids = [j['id'] for j in report._get_options_journals(options)]
        if not selected_journal_ids:
            return []

        self.env.cr.execute(
            """
            SELECT array_remove(ARRAY_AGG(DISTINCT account_account.id), NULL),
                   array_remove(ARRAY_AGG(DISTINCT account_payment_method_line.payment_account_id), NULL)
              FROM account_journal
         LEFT JOIN account_payment_method_line
                ON account_journal.id = account_payment_method_line.journal_id
         LEFT JOIN account_account
                ON account_journal.default_account_id = account_account.id
               AND account_account.account_type IN ('asset_cash', 'liability_credit_card')
             WHERE account_journal.id IN %s
               AND account_journal.type IN %s
            """,
            [tuple(selected_journal_ids), tuple(journal_types)],
        )
        res = self.env.cr.fetchall()[0]
        return list(set((res[0] or []) + (res[1] or [])))

    def _custom_options_initializer(self, report, options, previous_options):
        super()._custom_options_initializer(report, options, previous_options=previous_options)

        journal_types = self._get_book_journal_types()
        if journal_types:
            report._init_options_journals(
                options,
                previous_options=previous_options,
                additional_journals_domain=[('type', 'in', list(journal_types))],
            )
            report._init_options_journals_names(options, previous_options=previous_options)

            account_ids = self._get_book_account_ids(report, options)
            forced_domain = list(options.get('forced_domain') or [])
            if account_ids:
                forced_domain.append(('account_id', 'in', account_ids))
            else:
                # No liquidity account configured: return an empty report instead of all accounts.
                forced_domain.append(('account_id', '=', False))
            options['forced_domain'] = forced_domain

    def _custom_line_postprocessor(self, report, options, lines):
        """GL postprocessor without unaffected-earnings noise; uses this report's line."""
        if not lines:
            return lines

        processed_lines = []
        main_line_dict = None
        account_move_lines = []
        report_line_id = report.line_ids[:1].id

        for line in lines:
            markup, model, res_id = report._parse_line_id(line['id'])[-1]
            if model == 'account.report.line' and res_id == report_line_id:
                main_line_dict = line
            else:
                processed_lines.append(line)

            if (
                model is None and markup == {'groupby': 'id_with_accumulated_balance'}
                and not str(res_id).startswith('balance_line_')
                and options.get('export_mode') != 'file'
            ):
                line['chatter'] = {'id': json.loads(res_id)[1]}
                account_move_lines.append(line)

        if account_move_lines:
            line_ids = (aml['chatter']['id'] for aml in account_move_lines)
            account_moves = {
                line['id']: line['move_id'][0]
                for line in self.env['account.move.line'].browse(line_ids).read(['id', 'move_id'])
            }
            for line in account_move_lines:
                line['chatter']['id'] = account_moves[line['chatter']['id']]
                line['chatter']['model'] = 'account.move'

        if main_line_dict and not (
            self.env.company.totals_below_sections and not options.get('ignore_totals_below_sections')
        ):
            processed_lines.append({
                'id': report._get_generic_line_id(None, None, 'total'),
                'name': self._get_book_total_label(),
                'columns': main_line_dict['columns'],
                'level': 1,
            })

        return processed_lines


class AccountBankBookReportHandler(models.AbstractModel):
    _name = 'account.bank.book.report.handler'
    _inherit = 'account.book.report.handler'
    _description = 'Bank Book Report Handler'

    _book_journal_types = ('bank',)
    _book_total_label = 'Total Bank Book'


class AccountCashBookReportHandler(models.AbstractModel):
    _name = 'account.cash.book.report.handler'
    _inherit = 'account.book.report.handler'
    _description = 'Cash Book Report Handler'

    _book_journal_types = ('cash',)
    _book_total_label = 'Total Cash Book'


class AccountDayBookReportHandler(models.AbstractModel):
    _name = 'account.day.book.report.handler'
    _inherit = 'account.book.report.handler'
    _description = 'Day Book Report Handler'

    _book_journal_types = ()
    _book_total_label = 'Total Day Book'

    def _custom_options_initializer(self, report, options, previous_options):
        # Skip liquidity-account forcing from the shared book handler.
        super(AccountBookReportHandler, self)._custom_options_initializer(
            report, options, previous_options=previous_options
        )

    def _get_query(self, options, current_groupby, order_by_account=False, offset=0, limit=None):
        """Day Book only includes the selected period (no initial-balance carry)."""
        report = self.env['account.report'].browse(options['report_id'])
        additional_domain = []
        report_query = report._get_report_query(options, 'strict_range', additional_domain)

        if options.get('export_mode') == 'print' and options.get('filter_search_bar') and current_groupby not in ('id_with_accumulated_balance', 'id'):
            search_bar_sql = SQL(
                """
                AND account_move_line.account_id = ANY(%(search_bar_account_query)s)
                """,
                search_bar_account_query=self.env['account.account']._search([
                    ('display_name', 'ilike', options.get('filter_search_bar')),
                    *self.env['account.account']._check_company_domain(
                        self.env['account.report'].get_report_company_ids(options)
                    ),
                ]).select(SQL.identifier('id')),
            )
        else:
            search_bar_sql = SQL()

        additional_select = SQL("")
        groupby = []
        if current_groupby == 'id_with_accumulated_balance':
            account_code_select = self.env['account.account']._field_to_sql(
                'account_move_line__account_id', 'code', report_query
            )
            account_name_select = self.env['account.account']._field_to_sql(
                'account_move_line__account_id', 'name'
            )
            additional_select = SQL(
                """
                account_move_line.id AS id,
                account_move_line.date AS date,
                MIN(move.name) AS move_name,
                SUM(account_move_line.amount_currency) AS amount_currency,
                MIN(partner.name) AS partner_name,
                MIN(account_move_line.currency_id) AS currency_id,
                MIN(account_move_line__account_id.id) AS account_id,
                MIN(account_move_line.name) AS line_name,
                MIN(%(account_name_select)s) AS account_name,
                MIN(%(account_code_select)s) AS account_code,
                """,
                account_name_select=account_name_select,
                account_code_select=account_code_select,
            )
            groupby = [SQL("account_move_line.id"), SQL("account_move_line.date"), SQL("account_move_line.account_id")]
        elif current_groupby == 'date':
            additional_select = SQL("""
                account_move_line.date AS date,
            """)
            groupby = [SQL("account_move_line.date")]
        elif current_groupby:
            groupby_field_sql = self.env['account.move.line']._field_to_sql(
                'account_move_line', current_groupby, report_query
            )
            additional_select = SQL("%s AS %s,", groupby_field_sql, SQL.identifier(current_groupby))
            groupby = [groupby_field_sql]

        report_query.left_join('account_move_line', 'account_id', 'account_account', 'id', 'account_id')
        if current_groupby == 'date':
            order_clause = [SQL("account_move_line.date")]
        elif current_groupby == 'id_with_accumulated_balance':
            order_clause = [SQL("account_move_line.date, move_name, account_move_line.id")]
        else:
            order_clause = []

        return SQL(
            """
            SELECT
                %(additional_select)s
                COALESCE(SUM(%(select_debit)s), 0.0) AS debit,
                COALESCE(SUM(%(select_credit)s), 0.0) AS credit,
                COALESCE(SUM(%(select_balance)s), 0.0) AS balance
            FROM %(from_clause)s
            LEFT JOIN res_partner partner ON partner.id = account_move_line.partner_id
            JOIN account_move move ON move.id = account_move_line.move_id
            %(currency_table_join)s
            WHERE %(where_clause)s
            %(search_bar_sql)s
            %(additional_groupby)s
            %(orderby_clause)s
            %(offset_clause)s
            LIMIT %(limit)s
            """,
            additional_select=additional_select,
            select_balance=report._currency_table_apply_rate(SQL("account_move_line.balance")),
            select_debit=report._currency_table_apply_rate(SQL("account_move_line.debit")),
            select_credit=report._currency_table_apply_rate(SQL("account_move_line.credit")),
            from_clause=report_query.from_clause,
            currency_table_join=report._currency_table_aml_join(options),
            where_clause=report_query.where_clause,
            search_bar_sql=search_bar_sql,
            additional_groupby=SQL("GROUP BY %s", SQL(",").join(groupby)) if groupby else SQL(),
            orderby_clause=SQL("ORDER BY %s", SQL(",").join(order_clause)) if order_clause else SQL(),
            offset_clause=SQL("OFFSET %s", offset) if offset else SQL(),
            limit=limit,
        )

    def _report_custom_engine_general_ledger(self, expressions, options, date_scope, current_groupby, next_groupby, offset=0, limit=None, warnings=None):
        def get_grouping_key(row, groupby):
            if groupby == 'id_with_accumulated_balance':
                return json.dumps([str(row['date']), row['id']])
            if groupby == 'date':
                return fields.Date.to_string(row['date']) if row['date'] else None
            return row[groupby] if groupby else None

        query = self._get_query(options, current_groupby, offset=offset, limit=limit)
        rows_by_key = defaultdict(lambda: {
            'date': None,
            'partner_name': None,
            'amount_currency': None,
            'currency_id': self.env.company.currency_id.id,
            'debit': 0,
            'credit': 0,
            'balance': 0,
            'has_sublines': True,
        })

        for row in self.env.execute_query_dict(query):
            aml_key = get_grouping_key(row, current_groupby)
            if aml_key not in rows_by_key:
                rows_by_key[aml_key].update({
                    'debit': row['debit'],
                    'credit': row['credit'],
                    'balance': row['balance'],
                })
                if current_groupby == 'id_with_accumulated_balance':
                    rows_by_key[aml_key]['has_sublines'] = False
                    rows_by_key[aml_key]['date'] = row['date']
                    rows_by_key[aml_key]['partner_name'] = row['partner_name']
                    rows_by_key[aml_key]['line_name'] = row['line_name']
                    rows_by_key[aml_key]['account_code'] = row['account_code']
                    rows_by_key[aml_key]['account_name'] = row['account_name']
                    rows_by_key[aml_key]['move_name'] = row['move_name']
                    rows_by_key[aml_key]['account_id'] = row['account_id']
                    if row['currency_id'] != self.env.company.currency_id.id:
                        rows_by_key[aml_key]['amount_currency'] = row['amount_currency']
                        rows_by_key[aml_key]['currency_id'] = row['currency_id']
                elif current_groupby == 'date':
                    rows_by_key[aml_key]['date'] = row['date']
                    rows_by_key[aml_key]['has_sublines'] = True
            else:
                rows_by_key[aml_key]['debit'] += row['debit']
                rows_by_key[aml_key]['credit'] += row['credit']
                rows_by_key[aml_key]['balance'] += row['balance']

        if not current_groupby:
            return rows_by_key[None]
        return [(key, entry) for key, entry in rows_by_key.items()]

    def _report_expand_unfoldable_line_with_groupby(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        # Day book lines do not need GL-style accumulated running balance.
        report = self.env['account.report'].browse(options['report_id'])
        return report._report_expand_unfoldable_line_with_groupby(
            line_dict_id, groupby, options, progress, offset, unfold_all_batch_data
        )
