# -*- coding: utf-8 -*-
"""Shared building blocks for the per-bank statement parsers.

Every bank parser exposes ``parse(text) -> (rows, exceptions)``:

* ``rows`` are import-ready dicts (date, payment_ref, partner, amount)
* ``exceptions`` describe rows we refuse to trust

Two rules hold across all banks. The sign of an amount comes from the column
it was printed in, never from words in the narrative. Every amount is then
re-checked against the statement's own running balance, and a row whose
balance delta disagrees is reported instead of being silently imported.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

# Amounts printed with cents, e.g. "-1,715,000.00" or "3.75".
DECIMAL_AMOUNT = re.compile(r'-?\d[\d,]*\.\d{1,2}')
# Premier prints whole shillings without separators, e.g. "318794" or "0".
LOOSE_AMOUNT = re.compile(r'-?\d[\d,]*(?:\.\d{1,2})?')

# How far past a column header an amount may end and still belong to it.
# pdftotext right-aligns figures a few characters beyond the header word.
COLUMN_SLACK_LEFT = 6
COLUMN_SLACK_RIGHT = 14

BALANCE_TOLERANCE = 0.01


class Txn:
    """One parsed transaction, before validation."""

    __slots__ = ('date', 'ref', 'description', 'amount', 'balance', 'source')

    def __init__(self, date, ref, description, amount, balance, source=''):
        self.date = date
        self.ref = ref or ''
        self.description = description or ''
        self.amount = amount
        self.balance = balance
        self.source = source

    @property
    def payment_ref(self):
        parts = [p for p in (self.ref, squash(self.description)) if p]
        return ' | '.join(parts)


def squash(text):
    """Collapse runs of whitespace and trim separator punctuation."""
    return re.sub(r'\s+', ' ', text or '').strip(' |,-')


def parse_amount(raw):
    return float(str(raw).replace(',', '').replace(' ', ''))


def parse_date(raw, fmt):
    return datetime.strptime(raw, fmt).date()


def find_amounts(line, regex=DECIMAL_AMOUNT):
    """Return [(value, start, end)] for every amount token on ``line``."""
    return [(parse_amount(m.group()), m.start(), m.end())
            for m in regex.finditer(line)]


def build_column_map(lines, labels, scan_limit=80):
    """Locate the amount columns of a fixed-width statement.

    ``labels`` is an ordered list of ``(key, header_text)``. The header line is
    the line carrying the most labels; labels printed on a neighbouring line
    (Absa splits "Debit (KES)" off from "Credit") are picked up within two
    lines of it. Returns ``{key: (start, end)}`` of the header text spans.
    """
    header_index, best_hits = None, 0
    for index, line in enumerate(lines[:scan_limit]):
        hits = sum(1 for _, text in labels if text in line)
        if hits > best_hits:
            header_index, best_hits = index, hits
    if header_index is None:
        return {}

    columns = {}
    for key, text in labels:
        for offset in (0, 1, -1, 2, -2):
            index = header_index + offset
            if 0 <= index < len(lines) and text in lines[index]:
                start = lines[index].index(text)
                columns[key] = (start, start + len(text))
                break
    return columns


def column_of(end, columns):
    """Return the column key an amount ending at ``end`` belongs to.

    Amounts are matched to the nearest header whose band they fall in, so
    stray digits in the narrative (references, phone numbers) resolve to
    ``None`` and are ignored rather than parsed as money.
    """
    best_key, best_distance = None, None
    for key, (start, stop) in columns.items():
        if start - COLUMN_SLACK_LEFT <= end <= stop + COLUMN_SLACK_RIGHT:
            distance = abs(end - stop)
            if best_distance is None or distance < best_distance:
                best_key, best_distance = key, distance
    return best_key


def split_by_columns(line, columns, regex=DECIMAL_AMOUNT):
    """Map the amounts on ``line`` onto their columns.

    Returns ``(values, leftover_text)`` where ``values`` is ``{key: value}``
    and ``leftover_text`` is the line with the classified amounts blanked out,
    which is what remains of the description.
    """
    values = {}
    leftover = list(line)
    for value, start, end in find_amounts(line, regex):
        key = column_of(end, columns)
        if key is None or key in values:
            continue
        values[key] = value
        leftover[start:end] = ' ' * (end - start)
    return values, ''.join(leftover)


def signed_amount(values, debit_key='debit', credit_key='credit'):
    """Combine the debit and credit cells into one signed amount.

    Money out is negative, money in positive. The unused cell is printed as
    ``0``/``0.00`` by most banks and omitted entirely by Absa and Gulf.
    """
    debit = values.get(debit_key) or 0.0
    credit = values.get(credit_key) or 0.0
    return abs(credit) - abs(debit)


def group_records(lines, is_anchor, lead_last=False):
    """Group continuation lines around the transaction lines they belong to.

    Each record is ``(anchor_line, before_lines, after_lines)``. Wrapped
    description cells normally follow their transaction line, but KCB centres
    a multi-line cell vertically, so the line immediately above a transaction
    belongs to it. ``lead_last`` enables that reading.
    """
    anchors = [index for index, line in enumerate(lines) if is_anchor(line)]
    if not anchors:
        return []

    records = []
    for position, index in enumerate(anchors):
        gap_start = anchors[position - 1] + 1 if position else 0
        gap_end = anchors[position + 1] if position + 1 < len(anchors) else len(lines)
        before, after = [], []

        gap = [line for line in lines[gap_start:index] if line.strip()]
        if lead_last and gap:
            before = [gap[-1]]
        trailing = [line for line in lines[index + 1:gap_end] if line.strip()]
        if lead_last and trailing:
            # The last line of the gap leads the next transaction instead.
            has_next = position + 1 < len(anchors)
            after = trailing[:-1] if has_next else trailing
        else:
            after = trailing

        records.append((lines[index], before, after))
    return records


def build_rows(transactions, stated_opening=None, stated_closing=None,
               tolerance=BALANCE_TOLERANCE):
    """Validate chronological ``transactions`` and render import rows.

    Each amount is compared with the movement in the running balance column.
    Rows that disagree are still emitted (the column reading is the primary
    source) but are flagged low confidence and listed as exceptions, and zero
    value rows are dropped.

    The opening balance is reconstructed from the first transaction rather
    than trusted, because Gulf mislabels its opening as DR and Premier reports
    zero. A disagreement with the stated figure is reported once, against the
    statement, instead of poisoning the first row.
    """
    rows, exceptions = [], []
    previous_balance = stated_opening

    first = next((t for t in transactions
                  if t.balance is not None and t.amount is not None), None)
    if first is not None:
        reconstructed = round(first.balance - first.amount, 2)
        previous_balance = reconstructed
        if stated_opening is not None and abs(stated_opening - reconstructed) > tolerance:
            exceptions.append({
                'reason': 'opening_balance_mismatch',
                'detail': 'statement says %.2f, transactions imply %.2f' % (
                    stated_opening, reconstructed),
            })

    for txn in transactions:
        reference = txn.payment_ref
        confidence = 'high'

        if txn.amount is None:
            exceptions.append({
                'reason': 'no_amount',
                'detail': reference or txn.source.strip()[:160],
                'date': txn.date.isoformat(),
            })
            previous_balance = txn.balance
            continue

        if abs(txn.amount) < 0.005:
            exceptions.append({
                'reason': 'zero_amount',
                'detail': reference[:160],
                'date': txn.date.isoformat(),
            })
            previous_balance = txn.balance
            continue

        if txn.balance is not None and previous_balance is not None:
            delta = txn.balance - previous_balance
            if abs(delta - txn.amount) > tolerance:
                confidence = 'low'
                exceptions.append({
                    'reason': 'balance_mismatch',
                    'detail': '%s (running balance moved %.2f)' % (
                        reference[:120], delta),
                    'date': txn.date.isoformat(),
                    'amount': txn.amount,
                })
        elif txn.balance is None:
            confidence = 'med'

        if txn.balance is not None:
            previous_balance = txn.balance

        rows.append({
            'date': txn.date.isoformat(),
            'payment_ref': reference,
            'partner': '',
            'amount': '%.2f' % txn.amount,
            'confidence': confidence,
            'balance': txn.balance,
        })

    if stated_closing is not None and previous_balance is not None:
        if abs(stated_closing - previous_balance) > tolerance:
            exceptions.append({
                'reason': 'closing_balance_mismatch',
                'detail': 'statement says %.2f, parsed rows end at %.2f' % (
                    stated_closing, previous_balance),
            })

    return rows, exceptions


def rows_to_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=['date', 'payment_ref', 'partner', 'amount'])
    writer.writeheader()
    for row in rows:
        writer.writerow({
            'date': row['date'],
            'payment_ref': row['payment_ref'],
            'partner': row.get('partner') or '',
            'amount': row['amount'],
        })
    return buf.getvalue()


def empty_text_result():
    return [], [{'reason': 'empty_file', 'detail': 'No text to parse'}]


def no_rows_exception(bank_label):
    return {
        'reason': 'no_rows',
        'detail': (
            'Could not parse any %s transactions — the file may be scanned, '
            'image-only, or from a different bank.' % bank_label
        ),
    }
