from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestDailyPositionBillSync(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.env.user.group_ids |= cls.env.ref('purchase.group_purchase_manager')
        cls.env.user.group_ids |= cls.env.ref('account.group_account_user')
        cls.product_a.write({
            'fuel_ok': True,
            'default_code': 'PMS',
            'purchase_ok': True,
            'purchase_method': 'purchase',
            'is_storable': False,
            'taxes_id': [fields.Command.set([])],
            'supplier_taxes_id': [fields.Command.set([])],
        })
        cls.partner_b.supplier_rank = 1

    def _position(self, qty=100.0, price=10.0):
        return self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': qty,
            'buy_price': price,
        })

    def _qty_bills(self, po):
        return po._daily_position_quantity_bills().filtered(
            lambda move: move.state == 'posted')

    def _bill_qty_price(self, moves):
        lines = moves.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
            and line.product_id == self.product_a)
        return sum(lines.mapped('quantity')), (
            lines[:1].price_unit if lines else 0.0)

    def test_first_sync_posts_vendor_bill(self):
        position = self._position()
        position._sync_purchase_order_line()
        po = position.purchase_order_id
        bills = self._qty_bills(po)
        self.assertTrue(po.is_daily_position_po)
        self.assertEqual(po.order_line.product_qty, 100.0)
        self.assertEqual(len(bills), 1)
        self.assertEqual(bills.state, 'posted')
        qty, price = self._bill_qty_price(bills)
        self.assertEqual(qty, 100.0)
        self.assertEqual(price, 10.0)
        self.assertEqual(po.order_line.qty_invoiced, 100.0)
        self.assertEqual(po.order_line.qty_to_invoice, 0.0)

    def test_resync_increase_rewrites_unpaid_bill(self):
        position = self._position()
        position._sync_purchase_order_line()
        bill = self._qty_bills(position.purchase_order_id)
        position.write({'qty_bought': 150.0})
        position._sync_purchase_order_line()
        po = position.purchase_order_id
        bills = self._qty_bills(po)
        self.assertEqual(bills, bill)
        self.assertEqual(po.order_line.product_qty, 150.0)
        qty, price = self._bill_qty_price(bills)
        self.assertEqual(qty, 150.0)
        self.assertEqual(price, 10.0)
        self.assertEqual(po.order_line.qty_invoiced, 150.0)
        self.assertEqual(po.order_line.qty_to_invoice, 0.0)

    def test_resync_decrease_rewrites_unpaid_bill(self):
        position = self._position()
        position._sync_purchase_order_line()
        position.write({'qty_bought': 80.0})
        position._sync_purchase_order_line()
        po = position.purchase_order_id
        bills = self._qty_bills(po)
        self.assertEqual(len(bills), 1)
        qty, _price = self._bill_qty_price(bills)
        self.assertEqual(qty, 80.0)
        self.assertEqual(po.order_line.qty_invoiced, 80.0)
        self.assertEqual(po.order_line.qty_to_invoice, 0.0)

    def test_resync_price_rewrites_unpaid_bill(self):
        position = self._position()
        position._sync_purchase_order_line()
        position.write({'buy_price': 9.0})
        position._sync_purchase_order_line()
        po = position.purchase_order_id
        bills = self._qty_bills(po)
        self.assertEqual(len(bills), 1)
        qty, price = self._bill_qty_price(bills)
        self.assertEqual(qty, 100.0)
        self.assertEqual(price, 9.0)
        self.assertEqual(po.order_line.price_unit, 9.0)

    def test_noop_resync_does_not_create_another_bill(self):
        position = self._position()
        position._sync_purchase_order_line()
        first = self._qty_bills(position.purchase_order_id)
        position._sync_purchase_order_line()
        second = self._qty_bills(position.purchase_order_id)
        self.assertEqual(first, second)
        self.assertEqual(len(second), 1)

    def test_paid_bill_gets_delta_invoice_on_increase(self):
        position = self._position()
        position._sync_purchase_order_line()
        po = position.purchase_order_id
        original = self._qty_bills(po)
        self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=original.ids,
        ).create({}).action_create_payments()
        original.invalidate_recordset(['payment_state'])
        self.assertIn(original.payment_state, ('paid', 'in_payment'))

        position.write({'qty_bought': 130.0})
        position._sync_purchase_order_line()
        bills = self._qty_bills(po)
        self.assertEqual(len(bills), 2)
        self.assertIn(original, bills)
        orig_qty, orig_price = self._bill_qty_price(original)
        self.assertEqual(orig_qty, 100.0)
        self.assertEqual(orig_price, 10.0)
        delta = bills - original
        self.assertEqual(delta.move_type, 'in_invoice')
        delta_qty, delta_price = self._bill_qty_price(delta)
        self.assertEqual(delta_qty, 30.0)
        self.assertEqual(delta_price, 10.0)
        self.assertEqual(po.order_line.qty_invoiced, 130.0)
        self.assertEqual(po.order_line.qty_to_invoice, 0.0)

    def test_paid_bill_gets_refund_on_decrease(self):
        position = self._position()
        position._sync_purchase_order_line()
        po = position.purchase_order_id
        original = self._qty_bills(po)
        self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=original.ids,
        ).create({}).action_create_payments()

        position.write({'qty_bought': 70.0})
        position._sync_purchase_order_line()
        bills = self._qty_bills(po)
        refund = bills.filtered(lambda move: move.move_type == 'in_refund')
        self.assertEqual(len(refund), 1)
        refund_qty, refund_price = self._bill_qty_price(refund)
        self.assertEqual(refund_qty, 30.0)
        self.assertEqual(refund_price, 10.0)
        self.assertEqual(po.order_line.qty_invoiced, 70.0)
        self.assertEqual(po.order_line.qty_to_invoice, 0.0)

    def test_price_adjustment_does_not_rewrite_original_bill(self):
        position = self._position()
        position._sync_purchase_order_line()
        po = position.purchase_order_id
        original = self._qty_bills(po)
        credit = position._create_supplier_price_adjustment(
            10.0, 8.0, 40.0, 'Remaining reduction')
        credit.action_post()

        position.write({'qty_bought': 120.0})
        position._sync_purchase_order_line()
        qty_bills = self._qty_bills(po)
        self.assertIn(original, qty_bills)
        orig_qty, orig_price = self._bill_qty_price(original)
        self.assertEqual(orig_qty, 100.0)
        self.assertEqual(orig_price, 10.0)
        delta = qty_bills - original
        self.assertEqual(len(delta), 1)
        delta_qty, delta_price = self._bill_qty_price(delta)
        self.assertEqual(delta_qty, 20.0)
        self.assertEqual(delta_price, 10.0)
        self.assertEqual(credit.state, 'posted')
        self.assertEqual(po.order_line.qty_invoiced, 120.0)
