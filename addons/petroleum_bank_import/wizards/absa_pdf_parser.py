# -*- coding: utf-8 -*-
"""Absa PDF/text → CSV rows (MVP).

Parses text extracts like data/bank_statements_*/*_pdf.txt.
Does not invent partners; leaves partner blank.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime


DATE_START = re.compile(
    r'(?P<date>\d{2}/\d{2}/\d{4})\s+'
    r'(?P<ref>\S+)\s+'
    r'(?P<rest>.+)$'
)
AMOUNT = re.compile(r'-?[\d,]+\.\d{2}')


def _parse_date(date_str):
    return datetime.strptime(date_str, '%d/%m/%Y').date()


def _parse_amount(raw):
    return float(raw.replace(',', ''))


def parse_absa_statement_text(text):
    """Return (rows, exceptions).

    rows: list of dicts with date, payment_ref, partner, amount, confidence
    exceptions: low-confidence / unparsed notes
    """
    if not text or not text.strip():
        return [], [{'reason': 'empty_file', 'detail': 'No text to parse'}]

    if 'Absa' not in text and '2045130536' not in text and 'ABSA' not in text.upper():
        # Still try — operator may have stripped headers
        pass

    rows = []
    exceptions = []
    pending = None

    def flush_pending():
        nonlocal pending
        if not pending:
            return
        # Skip header / footer false starts
        ref = pending['ref']
        if not re.match(r'^\d{6,}$', ref) and not re.match(r'^[A-Za-z0-9]{8,}$', ref):
            exceptions.append({
                'reason': 'skipped_non_txn_ref',
                'detail': ref[:80],
                'date': pending['date'].isoformat(),
            })
            pending = None
            return

        rest = pending['rest']
        # Drop bank footer noise pulled into continuations
        rest = re.split(r'Absa Bank Kenya PLC\.|Page \d+', rest)[0]
        amounts = AMOUNT.findall(rest)
        particulars = AMOUNT.sub(' ', rest)
        particulars = re.sub(r'\s+', ' ', particulars).strip(' |')
        payment_ref = pending['ref']
        if particulars:
            payment_ref = f"{pending['ref']} | {particulars}"

        amount = None
        confidence = 'med'
        if len(amounts) >= 2:
            # Typically: [debit_or_credit, balance] or [debit, credit, balance]
            # Absa layout: Debit | Credit | Balance — one of debit/credit empty.
            # When two amounts: value + running balance.
            amount = _parse_amount(amounts[0])
            # Heuristic: fee/excise/debit words → outflow (negative)
            lower = particulars.lower()
            if any(k in lower for k in ('fee', 'excise', 'duty', 'charges')):
                amount = -abs(amount)
                confidence = 'high'
            elif 'rtgs' in lower or 'vitalac' in lower or 'transfer' in lower:
                confidence = 'med'
            else:
                confidence = 'med'
        elif len(amounts) == 1:
            amount = _parse_amount(amounts[0])
            confidence = 'low'
            exceptions.append({
                'reason': 'single_amount',
                'detail': payment_ref,
                'date': pending['date'].isoformat(),
            })
        else:
            exceptions.append({
                'reason': 'no_amount',
                'detail': payment_ref,
                'date': pending['date'].isoformat(),
            })
            pending = None
            return

        if abs(amount) < 0.0001:
            exceptions.append({
                'reason': 'zero_amount',
                'detail': payment_ref[:120],
                'date': pending['date'].isoformat(),
            })
            pending = None
            return

        # Debit vs credit from Absa column spacing is unreliable in text extracts.
        # Prefer sign from keywords; otherwise keep positive and flag.
        lower = particulars.lower()
        outflow_keys = (
            'fee', 'excise', 'duty', 'charges', 'rtgs in', 'bill//',
            'jameel vitalac', 'jameel premium', 'mpesab2c',
        )
        inflow_keys = ('petronet', 'reem jameel', 'cheque', 'purchases', 'zaynu')
        if any(k in lower for k in outflow_keys):
            amount = -abs(amount)
            confidence = 'high' if 'fee' in lower or 'excise' in lower else 'med'
        elif any(k in lower for k in inflow_keys):
            amount = abs(amount)
            confidence = 'med'
        else:
            exceptions.append({
                'reason': 'sign_uncertain',
                'detail': payment_ref,
                'date': pending['date'].isoformat(),
                'amount': amount,
            })
            confidence = 'low'

        rows.append({
            'date': pending['date'].isoformat(),
            'payment_ref': payment_ref,
            'partner': '',
            'amount': '%.2f' % amount,
            'confidence': confidence,
        })
        pending = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        m = DATE_START.search(line)
        if m:
            flush_pending()
            try:
                d = _parse_date(m.group('date'))
            except ValueError:
                exceptions.append({'reason': 'bad_date', 'detail': line.strip()[:120]})
                continue
            pending = {
                'date': d,
                'ref': m.group('ref'),
                'rest': m.group('rest'),
            }
        elif pending:
            # Continuation of particulars / amounts
            pending['rest'] = pending['rest'] + ' ' + line.strip()

    flush_pending()

    if not rows:
        exceptions.append({
            'reason': 'no_rows',
            'detail': 'Could not parse any Absa transactions — file may be scanned/image-only.',
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
