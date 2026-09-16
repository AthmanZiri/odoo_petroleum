# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models


def normalize_payment_ref(ref):
    """Collapse whitespace for stable duplicate fingerprints."""
    if not ref:
        return ''
    return re.sub(r'\s+', ' ', str(ref)).strip()


def statement_line_fingerprint(journal_id, date, amount, payment_ref):
    """Journal-scoped identity for import duplicate detection.

    Includes payment_ref so two same-day same-amount transfers are distinct.
    payment_ref is required by the CSV validator before this is used.
    """
    ref = normalize_payment_ref(payment_ref)
    amount_s = '%.2f' % float(amount or 0.0)
    date_s = fields.Date.to_string(date) if date else ''
    return f'{int(journal_id)}|{date_s}|{amount_s}|{ref}'


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    petro_statement_fingerprint = fields.Char(
        string='Import Fingerprint',
        index=True,
        copy=False,
        help='Used to skip duplicate bank statement imports.',
    )

    @api.model
    def _petro_fingerprint(self, journal_id, date, amount, payment_ref):
        return statement_line_fingerprint(journal_id, date, amount, payment_ref)

    @api.model
    def _petro_find_duplicate(self, journal_id, fingerprint, date=None, amount=None, payment_ref=None):
        """Return an existing non-cancelled line with this fingerprint (or legacy match)."""
        if fingerprint:
            found = self.search([
                ('journal_id', '=', journal_id),
                ('petro_statement_fingerprint', '=', fingerprint),
                ('move_id.state', '!=', 'cancel'),
            ], limit=1)
            if found:
                return found

        # Legacy lines imported before fingerprints existed
        if date is not None and amount is not None and payment_ref:
            ref = normalize_payment_ref(payment_ref)
            candidates = self.search([
                ('journal_id', '=', journal_id),
                ('date', '=', date),
                ('amount', '=', amount),
                ('move_id.state', '!=', 'cancel'),
            ], limit=20)
            for line in candidates:
                if normalize_payment_ref(line.payment_ref) == ref:
                    return line
        return self.browse()
