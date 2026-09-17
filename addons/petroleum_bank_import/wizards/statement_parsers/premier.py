# -*- coding: utf-8 -*-
"""Premier Bank Kenya — "Bank Account Statement" export.

Columns: Transaction Date | Description | Debits | Credits | Balance. Dates
are M/D/YYYY with a timestamp, figures are printed as whole shillings without
separators, and the unused money column holds a bare 0 — so amounts are read
from the column they sit in, which also keeps reference numbers inside the
description from being mistaken for money.

Records are separated by blank lines and the description cell is centred, so
it can appear above as well as below the figures. The statement summary
reports opening and closing balances of 0; both are ignored in favour of the
balance column.
"""
from __future__ import annotations

import re

from . import common

BANK_LABEL = 'Premier'

COLUMNS = [
    ('debit', 'Debits'),
    ('credit', 'Credits'),
    ('balance', 'Balance'),
]

TRANSACTION = re.compile(
    r'^\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M')
NOISE = re.compile(
    r'Bank Account Statement|Statement\s+Summary|Customer Profile|'
    r'Opening Balance|Closing Balance|Block Amount|Available Balance|'
    r'Statement Date|Transaction Date|Premier Bank Kenya|Note: The statement')


def detect(text):
    return 'Premier Bank Kenya' in text or (
        'Bank Account Statement' in text and 'Debits' in text and 'Credits' in text)


def parse(text):
    if not text or not text.strip():
        return common.empty_text_result()

    raw_lines = text.splitlines()
    columns = common.build_column_map(raw_lines, COLUMNS)

    transactions = []
    exceptions = []
    for block in _blocks(raw_lines):
        anchors = [index for index, line in enumerate(block)
                   if TRANSACTION.match(line)]
        if len(anchors) != 1:
            continue
        anchor = block[anchors[0]]
        match = TRANSACTION.match(anchor)
        try:
            date = common.parse_date(match.group('date'), '%m/%d/%Y')
        except ValueError:
            exceptions.append({'reason': 'bad_date', 'detail': anchor.strip()[:120]})
            continue

        values, leftover = common.split_by_columns(
            anchor, columns, regex=common.LOOSE_AMOUNT)
        description = [leftover[match.end():]]
        description += [line for index, line in enumerate(block)
                        if index != anchors[0]]

        transactions.append(common.Txn(
            date=date,
            ref='',
            description=' '.join(description),
            amount=common.signed_amount(values) if values else None,
            balance=values.get('balance'),
            source=anchor,
        ))

    rows, row_exceptions = common.build_rows(transactions)
    exceptions.extend(row_exceptions)
    if not rows:
        exceptions.append(common.no_rows_exception(BANK_LABEL))
    return rows, exceptions


def _blocks(lines):
    """Split the statement into the blank-line separated groups it prints."""
    block = []
    for line in lines:
        if line.strip() and not NOISE.search(line):
            block.append(line)
        elif block:
            yield block
            block = []
    if block:
        yield block
