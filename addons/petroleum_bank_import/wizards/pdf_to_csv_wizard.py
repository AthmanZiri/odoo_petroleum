# -*- coding: utf-8 -*-
import base64
import logging
import os
import subprocess
import tempfile

from odoo import _, fields, models
from odoo.exceptions import UserError

from . import statement_parsers
from .statement_parsers import rows_to_csv

_logger = logging.getLogger(__name__)


class PetroleumBankPdfToCsvWizard(models.TransientModel):
    _name = 'petroleum.bank.pdf.to.csv.wizard'
    _description = 'Bank PDF/Text to CSV'

    bank = fields.Selection(
        [
            ('absa', 'Absa'),
            ('kcb', 'KCB'),
            ('gulf', 'Gulf African'),
            ('premier', 'Premier'),
            ('equity', 'Equity'),
            ('other', 'Other (manual / unsupported)'),
        ],
        required=True,
        default='absa',
    )
    attachment = fields.Binary(string='PDF or text extract', required=True)
    file_name = fields.Char(required=True)
    result_csv = fields.Binary(string='CSV output', readonly=True)
    result_csv_name = fields.Char(readonly=True)
    exception_text = fields.Text(string='Exceptions / low confidence', readonly=True)
    row_count = fields.Integer(readonly=True)
    exception_count = fields.Integer(readonly=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done')],
        default='draft',
    )

    def action_convert(self):
        self.ensure_one()
        if self.bank == 'other':
            raise UserError(_(
                "No parser for this bank. Prepare a "
                "date,payment_ref,partner,amount CSV manually."
            ))

        text = self._extract_text()
        if self._looks_like_image_only(text):
            raise UserError(_(
                "This file looks scanned/image-only (little extractable text). "
                "Export a text statement from the bank or OCR it externally, "
                "then re-run this wizard on the text."
            ))

        self._check_bank_matches_file(text)

        rows, exceptions = statement_parsers.parse_statement_text(self.bank, text)
        if not rows:
            detail = '\n'.join(
                f"{e.get('reason')}: {e.get('detail')}" for e in exceptions
            ) or _('No detail')
            raise UserError(_(
                "No transactions parsed from %(bank)s file.\n%(detail)s",
                bank=statement_parsers.BANK_LABELS[self.bank],
                detail=detail,
            ))

        csv_text = rows_to_csv(rows)
        exc_lines = []
        for e in exceptions:
            parts = [e.get('reason') or '']
            if e.get('date'):
                parts.append(str(e['date']))
            if e.get('detail'):
                parts.append(str(e['detail'])[:160])
            if e.get('amount') is not None:
                parts.append(f"amount={e['amount']}")
            exc_lines.append(' | '.join(parts))

        base = os.path.splitext(self.file_name or 'statement')[0]
        self.write({
            'result_csv': base64.b64encode(csv_text.encode('utf-8')),
            'result_csv_name': f'{base}_import.csv',
            'exception_text': '\n'.join(exc_lines) or _('None'),
            'row_count': len(rows),
            'exception_count': len(exceptions),
            'state': 'done',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def _check_bank_matches_file(self, text):
        """Refuse to parse a statement with another bank's parser.

        Gulf African exports are labelled "Statement of Account" and are
        routinely mistaken for KCB; running the wrong parser would silently
        produce plausible but wrong rows.
        """
        detected = statement_parsers.detect_bank(text)
        if detected and detected != self.bank:
            raise UserError(_(
                "This file looks like a %(detected)s statement, but %(chosen)s "
                "was selected. Pick the matching bank and convert again.",
                detected=statement_parsers.BANK_LABELS[detected],
                chosen=statement_parsers.BANK_LABELS[self.bank],
            ))

    def action_download_csv_template(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/petroleum_bank_import/static/csv/bank_statement_import_template.csv',
            'target': 'new',
        }

    def _extract_text(self):
        raw = base64.b64decode(self.attachment)
        name = (self.file_name or '').lower()
        if name.endswith('.txt') or name.endswith('.csv'):
            return raw.decode('utf-8', errors='replace')

        # Try UTF-8 text anyway
        try:
            as_text = raw.decode('utf-8')
            if 'Date' in as_text or '/' in as_text[:2000]:
                return as_text
        except UnicodeDecodeError:
            pass

        if name.endswith('.pdf') or raw[:4] == b'%PDF':
            text = self._pdftotext(raw)
            if text is None:
                raise UserError(_(
                    "This server cannot read PDFs: the pdftotext tool is not "
                    "installed. Ask an administrator to install poppler-utils, "
                    "or upload a bank text extract (.txt) instead."
                ))
            if text.strip():
                return text
            raise UserError(_(
                "No text could be extracted from this PDF, so it is most likely "
                "scanned. Export a text statement from the bank and upload the "
                ".txt instead."
            ))

        return raw.decode('utf-8', errors='replace')

    def _pdftotext(self, raw):
        """Return the layout-preserving text, or None if pdftotext is missing.

        ``-layout`` is what keeps the figures in their printed columns, which
        is how the parsers tell a debit from a credit.
        """
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            try:
                proc = subprocess.run(
                    ['pdftotext', '-layout', tmp_path, '-'],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    return proc.stdout
                _logger.info('pdftotext failed: %s', proc.stderr)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except FileNotFoundError:
            _logger.warning(
                'pdftotext is not installed; the server cannot read bank PDFs')
            return None
        except Exception as err:
            _logger.info('pdftotext error: %s', err)
        return ''

    def _looks_like_image_only(self, text):
        if not text:
            return True
        letters = sum(c.isalpha() for c in text)
        return letters < 80
