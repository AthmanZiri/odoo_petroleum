# -*- coding: utf-8 -*-
"""Equity Bank — internet banking "Account Statement" export.

Columns: Transaction Date | Value Date | Narrative | Transaction Reference |
Debit | Credit | Running Balance. Both money columns are always printed, with
0.00 on the unused side, so the three trailing figures of a record give the
amount. The narrative may sit on the date line while the figures land on the
following line, so records are read as blocks rather than single lines.
"""
from __future__ import annotations

import re

from . import common

BANK_LABEL = 'Equity'

TRANSACTION = re.compile(
    r'^\s*(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<value_date>\d{2}/\d{2}/\d{4})')
REFERENCE = re.compile(r'(?P<ref>[A-Za-z]?\d{6,})\s*$')
SUMMARY = re.compile(r'Opening Balance\s+Total Debits')
END_OF_STATEMENT = re.compile(r'-+\s*End of Statement\s*-+')
NOISE = re.compile(
    r'Running Balance|Account Number:|Account Name:|Report generated on:|'
    r'IMPORTANT NOTICE|equitybank\.co\.ke|Internet Banking|^\s*Page \d+ of \d+')


def detect(text):
    return 'EQUITY BANK' in text.upper() or 'equitybank.co.ke' in text


def _summary_balances(lines):
    """Read the Opening/Closing figures printed under the summary headings."""
    for index, line in enumerate(lines):
        if not SUMMARY.search(line):
            continue
        for following in lines[index + 1:index + 4]:
            amounts = common.find_amounts(following)
            if len(amounts) >= 4:
                return amounts[0][0], amounts[-1][0]
    return None, None


def parse(text):
    if not text or not text.strip():
        return common.empty_text_result()

    raw_lines = text.splitlines()
    stated_opening, stated_closing = _summary_balances(raw_lines)

    body = []
    for line in raw_lines:
        if END_OF_STATEMENT.search(line):
            break
        if not NOISE.search(line):
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

        figures, reference, narrative = None, '', []
        for line in [anchor[match.end():]] + after:
            amounts = common.find_amounts(line)
            if figures is None and len(amounts) >= 3:
                figures = amounts[-3:]
                head = line[:figures[0][1]].rstrip()
                found = REFERENCE.search(head)
                if found:
                    reference = found.group('ref')
                    head = head[:found.start()]
                narrative.append(head)
            else:
                narrative.append(line)

        if figures is None:
            exceptions.append({
                'reason': 'no_amount',
                'detail': common.squash(' '.join([anchor] + after))[:160],
                'date': date.isoformat(),
            })
            continue

        debit, credit, balance = (value for value, _s, _e in figures)
        transactions.append(common.Txn(
            date=date,
            ref=reference,
            description=' '.join(narrative),
            amount=common.signed_amount({'debit': debit, 'credit': credit}),
            balance=balance,
            source=anchor,
        ))

    rows, row_exceptions = common.build_rows(
        transactions, stated_opening=stated_opening, stated_closing=stated_closing)
    exceptions.extend(row_exceptions)
    if not rows:
        exceptions.append(common.no_rows_exception(BANK_LABEL))
    return rows, exceptions
