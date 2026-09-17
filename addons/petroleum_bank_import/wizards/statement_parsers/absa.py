# -*- coding: utf-8 -*-
"""Absa Bank Kenya — "CASA Account Details" statement.

Columns: Date | Reference / Cheque Number | Transaction Particulars |
Debit (KES) | Credit (KES) | Balance (KES). Rows run newest first, the
particulars and reference wrap onto continuation lines, and the registered
office footer is repeated on every page.
"""
from __future__ import annotations

import re

from . import common

BANK_LABEL = 'Absa'

COLUMNS = [
    ('debit', 'Debit (KES)'),
    ('credit', 'Credit'),
    ('balance', 'Balance'),
]

TRANSACTION = re.compile(r'^\s*(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<ref>\S+)')
FOOTER = re.compile(r'Absa Bank Kenya PLC|^\s*Page \d+\s*/\s*\d+\s*$')
OPENING = re.compile(r'Opening balance\s+(?P<amount>[\d,]+\.\d{2})')
CLOSING = re.compile(r'Closing balance\s+(?P<amount>[\d,]+\.\d{2})')


def detect(text):
    return 'Absa' in text or 'ABSA' in text


def parse(text):
    if not text or not text.strip():
        return common.empty_text_result()

    lines = [line for line in text.splitlines() if not FOOTER.search(line)]
    columns = common.build_column_map(lines, COLUMNS)

    stated_opening = stated_closing = None
    body = []
    for line in lines:
        opening = OPENING.search(line)
        closing = CLOSING.search(line)
        if opening:
            stated_opening = common.parse_amount(opening.group('amount'))
        if closing:
            stated_closing = common.parse_amount(closing.group('amount'))
        if not (opening or closing):
            body.append(line)

    transactions = []
    exceptions = []
    for anchor, _before, after in common.group_records(
            body, lambda line: TRANSACTION.match(line) is not None):
        match = TRANSACTION.match(anchor)
        try:
            date = common.parse_date(match.group('date'), '%d/%m/%Y')
        except ValueError:
            exceptions.append({'reason': 'bad_date', 'detail': anchor.strip()[:120]})
            continue

        values, leftover = common.split_by_columns(anchor, columns)
        description = leftover[match.end('ref'):]

        transactions.append(common.Txn(
            date=date,
            ref=match.group('ref'),
            description=' '.join([description] + after),
            amount=common.signed_amount(values) if values else None,
            balance=values.get('balance'),
            source=anchor,
        ))

    # The PDF lists the newest transaction first; the balance column only
    # reconciles read forwards in time.
    transactions.reverse()

    rows, row_exceptions = common.build_rows(
        transactions, stated_opening=stated_opening, stated_closing=stated_closing)
    exceptions.extend(row_exceptions)
    if not rows:
        exceptions.append(common.no_rows_exception(BANK_LABEL))
    return rows, exceptions
