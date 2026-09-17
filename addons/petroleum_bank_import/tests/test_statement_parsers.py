# -*- coding: utf-8 -*-
"""Parser tests against the 1 Sep 2026 cut-over statements.

The fixtures are the ``pdftotext -layout`` extracts of the PDFs downloaded
for the cut-over, so the tests run without pdftotext installed. The expected
figures come from the accountant-verified conversion in
``data/bank_statements_2026-09-01/`` (COVER_SHEET.csv and OPERATOR_CHECKLIST.md).

Two of the statements misreport their own header figures — Gulf labels its
opening balance DR when the arithmetic says CR, and Premier prints 0/0 — so
the opening balances below are the reconstructed ones.
"""
import os

from odoo.tests import tagged, TransactionCase

from odoo.addons.petroleum_bank_import.wizards.statement_parsers import (
    parse_statement_text,
    rows_to_csv,
)

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')

# bank -> (fixture, rows, opening, closing)
STATEMENTS = {
    'absa': ('absa_statement.txt', 40, 7030219.95, 9153439.65),
    'kcb': ('kcb_statement.txt', 279, 115368.29, 2188492.04),
    'gulf': ('gulf_statement.txt', 13, 717.63, -1488.97),
    'premier': ('premier_statement.txt', 10, 113975.19, 2000.00),
}


def read_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as handle:
        return handle.read()


@tagged('post_install', '-at_install')
class TestStatementParsers(TransactionCase):

    def _parse(self, bank):
        rows, exceptions = parse_statement_text(bank, read_fixture(STATEMENTS[bank][0]))
        return rows, exceptions

    def test_row_counts_match_cover_sheet(self):
        for bank, (_fixture, expected_rows, _open, _close) in STATEMENTS.items():
            with self.subTest(bank=bank):
                rows, _exceptions = self._parse(bank)
                self.assertEqual(len(rows), expected_rows)

    def test_amounts_reconcile_opening_to_closing(self):
        """Opening + the signed amounts must land exactly on the closing balance."""
        for bank, (_fixture, _rows, opening, closing) in STATEMENTS.items():
            with self.subTest(bank=bank):
                rows, _exceptions = self._parse(bank)
                total = sum(float(row['amount']) for row in rows)
                self.assertAlmostEqual(opening + total, closing, places=2)
                self.assertAlmostEqual(rows[-1]['balance'], closing, places=2)

    def test_no_balance_mismatches(self):
        """Every amount must agree with the statement's own running balance."""
        for bank in STATEMENTS:
            with self.subTest(bank=bank):
                _rows, exceptions = self._parse(bank)
                mismatches = [e for e in exceptions if e['reason'] == 'balance_mismatch']
                self.assertFalse(mismatches, 'balance mismatches: %s' % mismatches)

    def test_rows_are_chronological(self):
        """Absa prints newest first; every parser must emit oldest first."""
        for bank in STATEMENTS:
            with self.subTest(bank=bank):
                rows, _exceptions = self._parse(bank)
                dates = [row['date'] for row in rows]
                self.assertEqual(dates, sorted(dates))

    def test_absa_signs_come_from_the_column_not_the_wording(self):
        rows, _exceptions = self._parse('absa')
        by_ref = {row['payment_ref']: float(row['amount']) for row in rows}
        # Credit column: money in, despite "JAMEEL" appearing in both directions.
        self.assertEqual(
            by_ref['85320831000100406093 | PETRONET JAMEEL 001100032026083'], 7100000.00)
        # Debit column: money out.
        self.assertEqual(
            by_ref['85320828000100270803 | JAMEEL VITALAC NAKURU'], -2030000.00)
        self.assertEqual(by_ref['85320828000100271157 | ABSA FEE'], -25.00)

    def test_kcb_drops_brought_forward_row(self):
        rows, _exceptions = self._parse('kcb')
        self.assertFalse([r for r in rows if 'B/FWD' in r['payment_ref'].upper()])
        self.assertTrue(rows[0]['payment_ref'].startswith('FT26213DGD09'))

    def test_kcb_joins_details_printed_above_the_figures(self):
        """KCB centres a wrapped details cell around its own amount line."""
        rows, _exceptions = self._parse('kcb')
        last = rows[-1]
        self.assertEqual(float(last['amount']), -1065.00)
        self.assertIn('Biashara Club Subscription', last['payment_ref'])
        self.assertIn('Fee', last['payment_ref'])

    def test_gulf_reads_dr_balances_as_negative(self):
        rows, _exceptions = self._parse('gulf')
        self.assertAlmostEqual(rows[-1]['balance'], -1488.97, places=2)
        self.assertEqual(float(rows[-1]['amount']), -500.00)

    def test_gulf_reports_its_mislabelled_opening_balance(self):
        _rows, exceptions = self._parse('gulf')
        reasons = [e['reason'] for e in exceptions]
        self.assertIn('opening_balance_mismatch', reasons)

    def test_premier_ignores_digits_inside_the_description(self):
        """"Cash Deposit # 579694" must not be read as a 579,694 movement."""
        rows, _exceptions = self._parse('premier')
        deposit = next(r for r in rows if '579694' in r['payment_ref'])
        self.assertEqual(float(deposit['amount']), 260665.00)

    def test_no_partner_is_invented(self):
        for bank in STATEMENTS:
            with self.subTest(bank=bank):
                rows, _exceptions = self._parse(bank)
                self.assertFalse([r for r in rows if r['partner']])

    def test_csv_output_shape(self):
        rows, _exceptions = self._parse('absa')
        csv_text = rows_to_csv(rows)
        lines = csv_text.strip().splitlines()
        self.assertEqual(lines[0], 'date,payment_ref,partner,amount')
        self.assertEqual(len(lines), len(rows) + 1)

    def test_empty_text(self):
        for bank in STATEMENTS:
            with self.subTest(bank=bank):
                rows, exceptions = parse_statement_text(bank, '')
                self.assertEqual(rows, [])
                self.assertEqual(exceptions[0]['reason'], 'empty_file')
