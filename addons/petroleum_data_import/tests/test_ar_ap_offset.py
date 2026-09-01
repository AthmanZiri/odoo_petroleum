from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestArApAutoOffset(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1

    def _invoice(self, amount, partner=None, date='2026-01-10', move_type='out_invoice', post=True):
        return self.init_invoice(
            move_type,
            partner=partner or self.partner_a,
            invoice_date=date,
            post=post,
            amounts=[amount],
            taxes=[],
        )

    def _payment(self, amount, partner=None, date='2026-01-15', post=True):
        return self.init_payment(
            amount,
            post=post,
            date=date,
            partner=partner or self.partner_a,
        )

    def _residual(self, move):
        return abs(move.amount_residual)

    def _ar_ap_residual(self, payment):
        lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type in (
                'asset_receivable', 'liability_payable',
            ))
        return abs(sum(lines.mapped('amount_residual')))

    def test_post_payment_offsets_invoice(self):
        invoice = self._invoice(100)
        self.assertEqual(invoice.payment_state, 'not_paid')
        payment = self._payment(100)
        self.assertEqual(invoice.payment_state, 'paid')
        self.assertEqual(self._residual(invoice), 0.0)
        self.assertEqual(self._ar_ap_residual(payment), 0.0)

    def test_partial_payment_leaves_invoice_residual(self):
        invoice = self._invoice(100)
        self._payment(40)
        self.assertEqual(invoice.payment_state, 'partial')
        self.assertEqual(self._residual(invoice), 60.0)

    def test_overpayment_leaves_unapplied_payment(self):
        invoice = self._invoice(100)
        payment = self._payment(150)
        self.assertEqual(invoice.payment_state, 'paid')
        self.assertEqual(self._residual(invoice), 0.0)
        self.assertAlmostEqual(self._ar_ap_residual(payment), 50.0)

    def test_fifo_oldest_invoice_first(self):
        first = self._invoice(100, date='2026-01-01')
        second = self._invoice(50, date='2026-01-05')
        self._payment(100, date='2026-01-10')
        self.assertEqual(first.payment_state, 'paid')
        self.assertEqual(self._residual(second), 50.0)

    def test_credit_note_offsets_oldest_invoice(self):
        invoice = self._invoice(100, date='2026-01-01')
        credit = self._invoice(100, date='2026-01-08', move_type='out_refund')
        self.assertEqual(self._residual(invoice), 0.0)
        self.assertEqual(self._residual(credit), 0.0)
        self.assertIn(invoice.payment_state, ('paid', 'reversed'))
        self.assertIn(credit.payment_state, ('paid', 'reversed'))

    def test_vendor_bill_and_payment(self):
        bill = self._invoice(80, partner=self.partner_b, move_type='in_invoice')
        payment = self._payment(-80, partner=self.partner_b)
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(self._residual(bill), 0.0)
        self.assertEqual(self._ar_ap_residual(payment), 0.0)

    def test_child_contact_invoice_parent_payment(self):
        child = self.env['res.partner'].create({
            'name': 'Delivery address',
            'parent_id': self.partner_a.id,
            'type': 'delivery',
        })
        invoice = self._invoice(100, partner=child)
        self._payment(100, partner=self.partner_a)
        self.assertEqual(invoice.payment_state, 'paid')

    def test_wizard_dry_run_does_not_write(self):
        invoice = self._invoice(100, post=False)
        invoice.with_context(petro_skip_auto_offset=True).action_post()
        payment = self._payment(100, post=False)
        payment.with_context(petro_skip_auto_offset=True).action_post()
        self.assertEqual(invoice.payment_state, 'not_paid')

        wizard = self.env['petroleum.ledger.reconcile'].create({
            'company_id': self.env.company.id,
            'dry_run': True,
            'only_imported': False,
        })
        wizard.action_reconcile()
        self.assertEqual(invoice.payment_state, 'not_paid')
        self.assertIn('Dry run', wizard.result_html)
        self.assertIn('FIFO match', wizard.result_html)

        wizard_run = self.env['petroleum.ledger.reconcile'].create({
            'company_id': self.env.company.id,
            'dry_run': False,
            'only_imported': False,
        })
        wizard_run.action_reconcile()
        self.assertEqual(invoice.payment_state, 'paid')

    def test_idempotent_second_run(self):
        invoice = self._invoice(100)
        self._payment(100)
        stats = self.env['account.move.line']._petro_fifo_offset(
            self.env.company, partner_ids=self.partner_a.ids)
        self.assertEqual(stats['matches'], 0)
        self.assertEqual(invoice.payment_state, 'paid')

    def test_cron_offsets_skipped_posts(self):
        invoice = self._invoice(100, post=False)
        invoice.with_context(petro_skip_auto_offset=True).action_post()
        payment = self._payment(100, post=False)
        payment.with_context(petro_skip_auto_offset=True).action_post()
        self.assertEqual(invoice.payment_state, 'not_paid')
        self.env['account.move.line']._petro_cron_auto_offset(
            batch_size=80, company_ids=self.env.company.ids)
        self.assertEqual(invoice.payment_state, 'paid')

    def test_payment_register_keeps_selected_invoice(self):
        older = self._invoice(100, date='2026-01-01')
        newer = self._invoice(100, date='2026-01-20')
        self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=newer.ids,
        ).create({
            'payment_date': fields.Date.from_string('2026-01-25'),
        })._create_payments()
        self.assertEqual(newer.payment_state, 'paid')
        self.assertEqual(older.payment_state, 'not_paid')

    def test_bulk_import_context_skips_offset(self):
        invoice = self.env['account.move'].with_context(
            petro_bulk_import=True,
        ).create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': '2026-01-10',
            'invoice_line_ids': [(0, 0, {
                'name': 'fuel',
                'price_unit': 100,
                'tax_ids': [(5, 0, 0)],
            })],
        })
        invoice.with_context(petro_bulk_import=True).action_post()
        payment = self._payment(100, post=False)
        payment.with_context(petro_bulk_import=True).action_post()
        self.assertEqual(invoice.payment_state, 'not_paid')
