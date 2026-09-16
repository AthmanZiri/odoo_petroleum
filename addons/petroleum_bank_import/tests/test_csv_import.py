# -*- coding: utf-8 -*-
import base64

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPetroBankCsvImport(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.company_data['default_journal_bank']

    def _import_csv(self, csv_text, file_name='test.csv'):
        wiz = self.env['import.bank.statement'].create({
            'journal_id': self.journal.id,
            'file_name': file_name,
            'attachment': base64.b64encode(csv_text.encode('utf-8')),
        })
        return wiz.action_statement_import()

    def test_import_then_duplicate_skip(self):
        csv_text = (
            "date,payment_ref,partner,amount\n"
            "2026-08-31,SMOKE REF 1 | ABSA FEE,,-25.00\n"
            "2026-08-31,SMOKE REF 2 | EXCISE,,-3.75\n"
        )
        self._import_csv(csv_text)
        lines = self.env['account.bank.statement.line'].search([
            ('journal_id', '=', self.journal.id),
            ('payment_ref', 'ilike', 'SMOKE REF'),
        ])
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(lines.mapped('petro_statement_fingerprint')))

        with self.assertRaises(UserError) as err:
            self._import_csv(csv_text)
        self.assertIn('Skipped duplicates: 2', str(err.exception))
        self.assertIn('Created: 0', str(err.exception))

        lines_after = self.env['account.bank.statement.line'].search([
            ('journal_id', '=', self.journal.id),
            ('payment_ref', 'ilike', 'SMOKE REF'),
        ])
        self.assertEqual(len(lines_after), 2)

    def test_validation_bad_date_fails_whole_file(self):
        csv_text = (
            "date,payment_ref,partner,amount\n"
            "2026-08-31,GOOD LINE,,-25.00\n"
            "not-a-date,BAD LINE,,-3.75\n"
        )
        before = self.env['account.bank.statement.line'].search_count([
            ('journal_id', '=', self.journal.id),
        ])
        with self.assertRaises(ValidationError) as err:
            self._import_csv(csv_text)
        self.assertIn('nothing was imported', str(err.exception))
        after = self.env['account.bank.statement.line'].search_count([
            ('journal_id', '=', self.journal.id),
        ])
        self.assertEqual(before, after)

    def test_working_sheet_without_payment_ref_rejected(self):
        csv_text = (
            "date,label,proposed_action,confidence,amount\n"
            "2026-08-31,ABSA FEE,fee,high,-25.00\n"
        )
        with self.assertRaises(ValidationError) as err:
            self._import_csv(csv_text)
        self.assertIn('working analysis sheet', str(err.exception))

    def test_prefers_payment_ref_over_label(self):
        csv_text = (
            "date,payment_ref,partner,amount,label\n"
            "2026-08-31,FULL BANK REF | ABSA FEE,,-25.00,ABSA FEE\n"
        )
        self._import_csv(csv_text)
        line = self.env['account.bank.statement.line'].search([
            ('journal_id', '=', self.journal.id),
            ('payment_ref', 'ilike', 'FULL BANK REF'),
        ], limit=1)
        self.assertTrue(line)
        self.assertIn('FULL BANK REF', line.payment_ref)
