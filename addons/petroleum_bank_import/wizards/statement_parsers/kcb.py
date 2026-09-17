# -*- coding: utf-8 -*-
"""KCB Bank — internet banking "Account Statement" export.

Columns: Transaction Date | Value Date | Transaction Details | Money Out |
Money In | Ledger Balance | Bank Reference Number, with dates as DD.MM.YYYY.

Money Out already carries its minus sign and the unused side is printed as
0.00, so the three trailing figures on a transaction line give the amount
without needing column geometry — which matters here because the indentation
shifts between page one and the rest of the export. The details cell is
centred vertically, so the line immediately above a transaction belongs to it.
"""
from __future__ import annotations

import re

from . import common

BANK_LABEL = 'KCB'

TRANSACTION = re.compile(
    r'^\s*(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<value_date>\d{2}\.\d{2}\.\d{4})')
REFERENCE = re.compile(r'\b(?P<ref>[A-Z]{2}\d{5}[A-Z0-9]{5})\s*$')
OPENING = re.compile(r'Balance At Period Start:\s*(?P<amount>-?[\d,]+\.\d{2})')
CLOSING = re.compile(r'Balance At Period End:\s*(?P<amount>-?[\d,]+\.\d{2})')
BROUGHT_FORWARD = re.compile(r'BALANCE\s+B/FWD', re.IGNORECASE)
HEADER_NOISE = re.compile(
    r'Transaction Details|Ledger Balance|Reference|Account Statement|'
    r'Available Balance|Total Money (In|Out)|Balance At Period|^\s*Page \d+',
    re.IGNORECASE)


def detect(text):
    return 'Money Out' in text and 'Ledger Balance' in text


def parse(text):
    if not text or not text.strip():
        return common.empty_text_result()

    stated_opening = stated_closing = None
    opening = OPENING.search(text)
    closing = CLOSING.search(text)
    if opening:
        stated_opening = common.parse_amount(opening.group('amount'))
    if closing:
        stated_closing = common.parse_amount(closing.group('amount'))

    lines = [line for line in text.splitlines() if not HEADER_NOISE.search(line)]

    transactions = []
    exceptions = []
    for anchor, before, after in common.group_records(
            lines, lambda line: TRANSACTION.match(line) is not None, lead_last=True):
        match = TRANSACTION.match(anchor)
        try:
            date = common.parse_date(match.group('date'), '%d.%m.%Y')
        except ValueError:
            exceptions.append({'reason': 'bad_date', 'detail': anchor.strip()[:120]})
            continue

        body = anchor[match.end():]
        reference = REFERENCE.search(body)
        if reference:
            body = body[:reference.start()]

        amounts = common.find_amounts(body)
        if len(amounts) < 3:
            if not BROUGHT_FORWARD.search(anchor):
                exceptions.append({
                    'reason': 'no_amount',
                    'detail': common.squash(anchor)[:160],
                    'date': date.isoformat(),
                })
            continue

        money_out, money_in, balance = (value for value, _s, _e in amounts[-3:])
        description_span = body[:amounts[-3][1]]

        if BROUGHT_FORWARD.search(anchor):
            # Opening row, not a movement — it only carries the balance.
            stated_opening = balance
            continue

        transactions.append(common.Txn(
            date=date,
            ref=reference.group('ref') if reference else '',
            description=' '.join(before + [description_span] + after),
            amount=common.signed_amount({'debit': money_out, 'credit': money_in}),
            balance=balance,
            source=anchor,
        ))

    rows, row_exceptions = common.build_rows(
        transactions, stated_opening=stated_opening, stated_closing=stated_closing)
    exceptions.extend(row_exceptions)
    if not rows:
        exceptions.append(common.no_rows_exception(BANK_LABEL))
    return rows, exceptions
