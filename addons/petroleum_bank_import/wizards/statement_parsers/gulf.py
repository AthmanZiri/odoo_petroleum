# -*- coding: utf-8 -*-
"""Gulf African Bank — "Statement of Account" (SOA) export.

Columns: Trade Date | Value Date | Description | Debit (KES) | Credit (KES) |
Balance. Balances carry a CR/DR suffix, descriptions wrap over as many as six
lines, and the whole account header block repeats on every page.

Not to be confused with KCB: the SOA filename carries the account number, and
Gulf is the only one of our banks that prints DR/CR against every balance.
"""
from __future__ import annotations

import re

from . import common

BANK_LABEL = 'Gulf African'

COLUMNS = [
    ('debit', 'Debit (KES)'),
    ('credit', 'Credit (KES)'),
    ('balance', 'Balance'),
]

TRANSACTION = re.compile(
    r'^\s*(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<value_date>\d{2}/\d{2}/\d{4})\s')
SIGNED_BALANCE = re.compile(r'(?P<amount>-?[\d,]+\.\d{2})\s*(?P<sign>CR|DR)\s*$')
LABELLED_BALANCE = re.compile(
    r'(?P<label>Opening|Closing) Balance \(KES\):', re.IGNORECASE)
BARE_BALANCE = re.compile(r'^\s*[\d,]+\.\d{2}\s*(CR|DR)\s*$')
PAGE_NOISE = re.compile(
    r'Trade Date|Statement of Account|^Date:|^Name:|^Account No:|'
    r'^Account Available Balance:|^Blocked Balance:|Disclaimer|gab\.co\.ke|'
    r'Total From ')


def detect(text):
    return 'gab.co.ke' in text or ('Trade Date' in text and 'Statement of Account' in text)


def _balance_of(line):
    match = SIGNED_BALANCE.search(line)
    if not match:
        return None
    amount = common.parse_amount(match.group('amount'))
    return -amount if match.group('sign') == 'DR' else amount


def parse(text):
    if not text or not text.strip():
        return common.empty_text_result()

    raw_lines = text.splitlines()
    columns = common.build_column_map(raw_lines, COLUMNS)

    stated = {}
    lines = []
    pending_label = None
    for line in raw_lines:
        label = LABELLED_BALANCE.search(line)
        if label:
            pending_label = label.group('label').lower()
            continue
        if pending_label and BARE_BALANCE.match(line):
            stated[pending_label] = _balance_of(line)
            pending_label = None
            continue
        pending_label = None
        if not PAGE_NOISE.search(line):
            lines.append(line)

    transactions = []
    exceptions = []
    for anchor, _before, after in common.group_records(
            lines, lambda line: TRANSACTION.match(line) is not None):
        match = TRANSACTION.match(anchor)
        try:
            date = common.parse_date(match.group('date'), '%d/%m/%Y')
        except ValueError:
            exceptions.append({'reason': 'bad_date', 'detail': anchor.strip()[:120]})
            continue

        values, leftover = common.split_by_columns(anchor, columns)
        head = re.sub(r'\s+(CR|DR)\s*$', '', leftover[match.end():])
        transactions.append(common.Txn(
            date=date,
            ref='',
            description=' '.join([head] + after),
            amount=common.signed_amount(values) if values else None,
            balance=_balance_of(anchor),
            source=anchor,
        ))

    rows, row_exceptions = common.build_rows(
        transactions,
        stated_opening=stated.get('opening'),
        stated_closing=stated.get('closing'))
    exceptions.extend(row_exceptions)
    if not rows:
        exceptions.append(common.no_rows_exception(BANK_LABEL))
    return rows, exceptions
