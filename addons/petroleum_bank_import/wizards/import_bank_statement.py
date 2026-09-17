# -*- coding: utf-8 -*-
import base64
import csv
import io
import os
import re
from datetime import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.petroleum_bank_import.models.account_bank_statement_line import (
    normalize_payment_ref,
)

# Columns allowed in import CSVs (extras ignored)
CORE_HEADERS = {'date', 'payment_ref', 'partner', 'amount'}
IGNORED_HEADERS = {
    'label', 'proposed_action', 'confidence', 'notes', 'note',
    'debit', 'credit', 'balance', 'running_balance',
}
WORKING_ONLY_HINTS = {'proposed_action', 'confidence'}


class ImportBankStatement(models.TransientModel):
    _inherit = 'import.bank.statement'

    def action_download_csv_template(self):
        """Download the standard bank statement CSV template."""
        return {
            'type': 'ir.actions.act_url',
            'url': '/petroleum_bank_import/static/csv/bank_statement_import_template.csv',
            'target': 'new',
        }

    def action_statement_import(self):
        self.ensure_one()
        if not self.file_name:
            raise ValidationError(_("Choose a file to import."))
        ext = os.path.splitext(self.file_name)[1].lower()
        if ext == '.csv':
            return self._petro_import_csv()
        return super().action_statement_import()

    # -------------------------------------------------------------------------
    # CSV pipeline
    # -------------------------------------------------------------------------

    def _petro_import_csv(self):
        journal = self.journal_id
        if not journal:
            raise ValidationError(_("Select a bank journal before importing."))
        if journal.type not in ('bank', 'cash'):
            raise ValidationError(_("Journal must be a Bank or Cash journal."))
        if not journal.default_account_id:
            raise ValidationError(_(
                "Journal %s has no default account. Set it before importing."
            ) % journal.display_name)

        try:
            raw = base64.b64decode(self.attachment)
            text = raw.decode('utf-8-sig')
        except Exception as err:
            raise ValidationError(_("Error reading CSV file: %s") % err) from err

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValidationError(_("CSV has no header row."))

        header_map = {self._petro_norm_header(h): h for h in reader.fieldnames if h}
        self._petro_validate_headers(header_map)

        parsed_rows = []
        errors = []
        for idx, row in enumerate(reader, start=2):  # 1 = header
            if not any((v or '').strip() for v in row.values()):
                continue
            try:
                parsed_rows.append(self._petro_parse_csv_row(row, header_map, idx))
            except ValidationError as err:
                errors.append(str(err))

        if errors:
            raise ValidationError(_(
                "CSV validation failed — nothing was imported.\n\n%s"
            ) % '\n'.join(errors[:40]))

        if not parsed_rows:
            raise ValidationError(_("CSV has no data rows."))

        return self._petro_create_from_rows(parsed_rows)

    def _petro_norm_header(self, name):
        return re.sub(r'\s+', ' ', (name or '').strip().lower())

    def _petro_validate_headers(self, header_map):
        keys = set(header_map)
        if 'amount' not in keys:
            raise ValidationError(_(
                "CSV must include an 'amount' column "
                "(signed: positive = money in, negative = money out)."
            ))
        if 'date' not in keys:
            raise ValidationError(_("CSV must include a 'date' column."))
        if 'payment_ref' not in keys and 'label' not in keys and 'name' not in keys:
            raise ValidationError(_(
                "CSV must include a 'payment_ref' column (or label/name)."
            ))
        # Warn-style hard fail: working sheet used without payment_ref
        if 'payment_ref' not in keys and WORKING_ONLY_HINTS & keys:
            raise ValidationError(_(
                "This looks like a working analysis sheet (proposed_action/confidence) "
                "without payment_ref. Export a clean "
                "date,payment_ref,partner,amount CSV before import."
            ))

    def _petro_parse_csv_row(self, row, header_map, line_no):
        def get(*names):
            for n in names:
                key = self._petro_norm_header(n)
                if key in header_map:
                    val = row.get(header_map[key])
                    if val is not None and str(val).strip() != '':
                        return str(val).strip()
            return None

        # Prefer explicit payment_ref over label/name (working CSVs have both)
        payment_ref = get('payment_ref', 'line_ids/payment_ref')
        if not payment_ref:
            payment_ref = get('label', 'name', 'description', 'reference')
        payment_ref = normalize_payment_ref(payment_ref)
        if not payment_ref:
            raise ValidationError(_(
                "Line %(line)s: payment_ref is required (empty ref is not allowed)."
            ) % {'line': line_no})

        date_raw = get('date', 'transaction date', 'line_ids/date')
        if not date_raw:
            raise ValidationError(_("Line %(line)s: date is required.") % {'line': line_no})
        transaction_date = self._petro_parse_date_strict(date_raw, line_no)

        amount_raw = get('amount', 'line_ids/amount', 'value')
        if amount_raw is None:
            raise ValidationError(_("Line %(line)s (%(ref)s): amount is required.") % {
                'line': line_no, 'ref': payment_ref,
            })
        amount = self._petro_parse_amount_strict(amount_raw, line_no, payment_ref)
        if amount == 0.0:
            raise ValidationError(_("Line %(line)s (%(ref)s): amount cannot be 0.") % {
                'line': line_no, 'ref': payment_ref,
            })

        partner_name = get(
            'partner', 'partner_id/name', 'payee', 'customer', 'supplier',
        )
        partner = False
        if partner_name:
            partner = self.env['res.partner'].search(
                [('name', '=', partner_name)], limit=1,
            )
            # Do not invent / do not fail — leave blank if unknown

        return {
            'date': transaction_date,
            'payment_ref': payment_ref,
            'amount': amount,
            'partner_id': partner.id if partner else False,
            'partner_name': partner_name or False,
            'line_no': line_no,
        }

    def _petro_parse_date_strict(self, date_str, line_no):
        date_str = str(date_str).strip().strip('"').strip("'")
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
            try:
                return datetime.strptime(date_str, fmt).date()
            except (ValueError, TypeError):
                continue
        try:
            res = fields.Date.from_string(date_str)
            if res:
                return res
        except Exception:
            pass
        raise ValidationError(_(
            "Line %(line)s: cannot parse date '%(date)s'."
        ) % {'line': line_no, 'date': date_str})

    def _petro_parse_amount_strict(self, val, line_no, payment_ref):
        if isinstance(val, (int, float)):
            return float(val)
        clean = str(val).strip().replace('"', '').replace("'", '')
        clean = clean.replace(',', '').replace(' ', '')
        for symbol in ('$', '€', '£', '¥', '₹', 'KES', 'kes'):
            clean = clean.replace(symbol, '')
        if clean.startswith('(') and clean.endswith(')'):
            clean = '-' + clean[1:-1]
        try:
            return float(clean)
        except (ValueError, TypeError) as err:
            raise ValidationError(_(
                "Line %(line)s (%(ref)s): cannot parse amount '%(amount)s'."
            ) % {'line': line_no, 'ref': payment_ref, 'amount': val}) from err

    def _petro_create_from_rows(self, parsed_rows):
        journal = self.journal_id
        StLine = self.env['account.bank.statement.line']
        line_cmds = []
        created = 0
        skipped = 0
        skipped_refs = []

        # Also skip duplicates within the same file
        seen_in_file = set()

        for row in parsed_rows:
            fp = StLine._petro_fingerprint(
                journal.id, row['date'], row['amount'], row['payment_ref'],
            )
            if fp in seen_in_file:
                skipped += 1
                skipped_refs.append(row['payment_ref'])
                continue
            seen_in_file.add(fp)

            if StLine._petro_find_duplicate(
                journal.id, fp,
                date=row['date'], amount=row['amount'],
                payment_ref=row['payment_ref'],
            ):
                skipped += 1
                skipped_refs.append(row['payment_ref'])
                continue

            vals = {
                'date': row['date'],
                'payment_ref': row['payment_ref'],
                'journal_id': journal.id,
                'amount': row['amount'],
                'petro_statement_fingerprint': fp,
            }
            if row.get('partner_id'):
                vals['partner_id'] = row['partner_id']
            if row.get('partner_name') and not row.get('partner_id'):
                if 'partner_name' in StLine._fields:
                    vals['partner_name'] = row['partner_name']
            line_cmds.append((0, 0, vals))
            created += 1

        statement = False
        if line_cmds:
            dates = [r['date'] for r in parsed_rows]
            statement = self.env['account.bank.statement'].create({
                'name': _('%(file)s (%(journal)s)') % {
                    'file': self.file_name,
                    'journal': journal.code,
                },
                'journal_id': journal.id,
                'company_id': journal.company_id.id,
                'date': max(dates),
                'balance_start': 0.0,
                'balance_end_real': 0.0,
                'line_ids': line_cmds,
            })

        message = _(
            "Import finished for %(journal)s.\n"
            "Created: %(created)s\n"
            "Skipped duplicates: %(skipped)s"
        ) % {
            'journal': journal.display_name,
            'created': created,
            'skipped': skipped,
        }
        if skipped_refs:
            unique_skip = list(dict.fromkeys(skipped_refs))[:15]
            message += '\n' + _('Examples skipped: %s') % '; '.join(unique_skip)

        if created == 0:
            raise UserError(message)

        # Open bank reconciliation for unmatched lines of this statement.
        # Build from the stored action so it carries `views`: the web client
        # does not derive them from `view_mode` for action dicts it receives.
        action = self.env['ir.actions.actions']._for_xml_id(
            'bank_reconciliation.action_bank_reconciliation'
        )
        action['domain'] = [('statement_id', '=', statement.id)]
        action['context'] = {
            'default_journal_id': journal.id,
            'search_default_journal_id': journal.id,
            'search_default_not_matched': 1,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bank statement import'),
                'message': message,
                'type': 'success',
                'sticky': True,
                'next': action,
            },
        }
