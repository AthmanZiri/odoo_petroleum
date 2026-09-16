# -*- coding: utf-8 -*-
from odoo.tests import tagged, TransactionCase

from odoo.addons.petroleum_bank_import.wizards.absa_pdf_parser import (
    parse_absa_statement_text,
    rows_to_csv,
)


SAMPLE = """
CASA Account Details
2045130536 - Absa One Biashara Account KES
Absa Bank Kenya PLC
                        Date                                                            Transaction Particulars                           Debit (KES)
                        31/08/2026 85320831000100406093                                 PETRONET JAMEEL                                                           7,100,000.00             9,153,439.65
                        31/08/2026 85320831000100969517                                 EXCISE DUTY FOR THE FEE                                          3.75                                  52,439.65
                                                                                        FUND TRANSFER WITHIN
                        31/08/2026 85320831000100969517                                                                                                25.00                                   52,443.40
                                                                                        ABSA FEE
"""


@tagged('post_install', '-at_install')
class TestAbsaPdfParser(TransactionCase):

    def test_parse_sample_rows(self):
        rows, exceptions = parse_absa_statement_text(SAMPLE)
        self.assertGreaterEqual(len(rows), 2)
        refs = ' '.join(r['payment_ref'] for r in rows)
        self.assertIn('PETRONET', refs)
        self.assertTrue(any(float(r['amount']) < 0 for r in rows))
        csv_text = rows_to_csv(rows)
        self.assertIn('date,payment_ref,partner,amount', csv_text)

    def test_empty_text(self):
        rows, exceptions = parse_absa_statement_text('')
        self.assertEqual(rows, [])
        self.assertTrue(exceptions)
