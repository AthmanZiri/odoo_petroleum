from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestBankJournalFromAccount(AccountTestInvoicingCommon):

    def test_creating_bank_gl_opens_cash_book(self):
        account = self.env['account.account'].create({
            'name': 'Equity Bank New Branch',
            'code': 'BNKEQ1',
            'account_type': 'asset_cash',
            'company_ids': self.env.company.ids,
        })
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.env.company.id),
            ('default_account_id', '=', account.id),
            ('type', 'in', ('bank', 'cash')),
        ], limit=1)
        self.assertTrue(journal, 'Bank and Cash GL must get a Bank/Cash journal')
        self.assertEqual(journal.type, 'bank')
        self.assertIn(journal, self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', self.env.company.id),
            ('default_account_id', '!=', False),
        ]))

    def test_cash_named_account_gets_cash_journal(self):
        account = self.env['account.account'].create({
            'name': 'Petty Cash Office',
            'code': 'CSHPC1',
            'account_type': 'asset_cash',
            'company_ids': self.env.company.ids,
        })
        journal = self.env['account.journal'].search([
            ('default_account_id', '=', account.id),
        ], limit=1)
        self.assertEqual(journal.type, 'cash')

    def test_creating_bank_journal_does_not_duplicate(self):
        journals_before = self.env['account.journal'].search_count([
            ('company_id', '=', self.env.company.id),
            ('type', '=', 'bank'),
        ])
        self.env['account.journal'].create({
            'name': 'Standalone Bank Book',
            'code': 'SBB1',
            'type': 'bank',
            'company_id': self.env.company.id,
        })
        journals_after = self.env['account.journal'].search_count([
            ('company_id', '=', self.env.company.id),
            ('type', '=', 'bank'),
        ])
        self.assertEqual(journals_after, journals_before + 1)

    def test_interbank_lists_new_journal(self):
        account = self.env['account.account'].create({
            'name': 'KCB Float Account',
            'code': 'BNKKCB',
            'account_type': 'asset_cash',
            'company_ids': self.env.company.ids,
        })
        journal = self.env['account.journal'].search([
            ('default_account_id', '=', account.id),
        ], limit=1)
        domain_journals = self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', self.env.company.id),
            ('default_account_id', '!=', False),
        ])
        self.assertIn(journal, domain_journals)
