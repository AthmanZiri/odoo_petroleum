from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestStaffClaimsJournal(AccountTestInvoicingCommon):

    def test_ensure_staff_claims_replaces_purchase_default(self):
        purchase = self.company_data['default_journal_purchase']
        self.env.company.expense_journal_id = purchase
        self.env.company._petroleum_ensure_staff_claims_journal()
        journal = self.env.company.expense_journal_id
        self.assertTrue(journal)
        self.assertEqual(journal.type, 'general')
        self.assertEqual(journal.code, 'STCLM')
        self.assertNotEqual(journal, purchase)

    def test_post_wizard_refuses_purchase_journal(self):
        self.env.company._petroleum_ensure_staff_claims_journal()
        wiz = self.env['hr.expense.post.wizard'].create({
            'employee_journal_id': self.company_data['default_journal_purchase'].id,
        })
        with self.assertRaises(UserError):
            wiz.action_post_entry()
