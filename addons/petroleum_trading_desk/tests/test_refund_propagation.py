from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestRefundPropagation(AccountTestInvoicingCommon):

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
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.truck = cls.env['truck.management'].create({
            'name': 'KCC 003C',
            'capacity': 200.0,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _synced_position(self, qty=100.0, price=10.0):
        position = self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': qty,
            'buy_price': price,
        })
        position._sync_purchase_order_line()
        return position

    def _posted_bill(self, position):
        return position.purchase_order_id._daily_position_quantity_bills().filtered(
            lambda move: move.state == 'posted'
            and move.move_type == 'in_invoice')

    def _reverse(self, move, quantity=None):
        reversal = move._reverse_moves([{'invoice_date': fields.Date.today()}])
        if quantity is not None:
            reversal.invoice_line_ids.filtered(
                lambda line: line.product_id == self.product_a
            ).quantity = quantity
        return reversal

    def _confirmed_deal(self, quantity=100.0):
        position = self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_opening': 150.0,
            'buy_price': 7.0,
            'sell_price': 10.0,
        })
        deal = self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'date': fields.Date.today(),
            'truck_id': self.truck.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': quantity,
                'sell_price': 10.0,
                'buy_price': 7.0,
                'supplier_id': self.partner_b.id,
                'position_line_id': position.id,
            })],
        })
        deal.action_confirm()
        return deal, position

    def _post_customer_invoice(self, deal):
        invoices = deal.sale_order_id._create_invoices()
        invoices.write({
            'deal_id': deal.id,
            'invoice_date': fields.Date.today(),
        })
        for line in invoices.invoice_line_ids.filtered(
                lambda inv_line: inv_line.product_id == self.product_a):
            line.petro_buy_price = 7.0
        invoices.action_post()
        return invoices

    # ------------------------------------------------------------------
    # Vendor side
    # ------------------------------------------------------------------

    def test_vendor_partial_reversal_reduces_lot(self):
        position = self._synced_position()
        bill = self._posted_bill(position)
        refund = self._reverse(bill, quantity=30.0)
        refund.action_post()

        self.assertTrue(refund.petro_qty_propagated)
        self.assertEqual(position.qty_bought, 70.0)
        self.assertEqual(position.qty_remaining, 70.0)
        self.assertEqual(
            position.purchase_order_line_id.product_qty, 70.0)
        history = position.price_history_ids.filtered(
            lambda h: h.reason == 'quantity_revision')
        self.assertEqual(len(history), 1)
        self.assertEqual(history.old_quantity, 100.0)
        self.assertEqual(history.new_quantity, 70.0)

    def test_vendor_refund_exceeding_remaining_blocked(self):
        position = self._synced_position()
        bill = self._posted_bill(position)
        deal = self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': 80.0,
                'sell_price': 12.0,
                'buy_price': 10.0,
                'supplier_id': self.partner_b.id,
            })],
        })
        self.env['petroleum.daily.position.allocation'].create({
            'position_line_id': position.id,
            'deal_id': deal.id,
            'deal_line_id': deal.line_ids.id,
            'quantity': 80.0,
            'buy_price': 10.0,
        })
        self.assertEqual(position.qty_remaining, 20.0)

        refund = self._reverse(bill)  # full 100 L
        with self.assertRaises(UserError) as error:
            refund.action_post()
        self.assertIn('remain unsold', str(error.exception))

    def test_vendor_refund_reset_to_draft_restores_litres(self):
        position = self._synced_position()
        bill = self._posted_bill(position)
        refund = self._reverse(bill, quantity=30.0)
        refund.action_post()
        self.assertEqual(position.qty_remaining, 70.0)

        refund.button_draft()

        self.assertFalse(refund.petro_qty_propagated)
        self.assertEqual(position.qty_bought, 100.0)
        self.assertEqual(position.qty_remaining, 100.0)
        self.assertEqual(
            position.purchase_order_line_id.product_qty, 100.0)

    def test_sync_created_refund_does_not_propagate(self):
        position = self._synced_position()
        po = position.purchase_order_id
        refund = po._create_daily_position_qty_refund(
            po.order_line, 20.0)

        self.assertEqual(refund.state, 'posted')
        self.assertFalse(refund.petro_qty_propagated)
        self.assertEqual(position.qty_bought, 100.0)
        self.assertFalse(position.price_history_ids.filtered(
            lambda h: h.reason == 'quantity_revision'))

    def test_position_wizard_quantity_note_does_not_propagate(self):
        position = self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 100.0,
            'buy_price': 10.0,
        })
        result = position.action_revise_lot_quantity(80.0, note='Short delivery')
        note = result['adjustment_move']
        self.assertEqual(position.qty_bought, 80.0)

        note.action_post()

        self.assertFalse(note.petro_qty_propagated)
        self.assertEqual(position.qty_bought, 80.0)

    def test_vendor_refund_excluded_from_supplier_margin_adjustments(self):
        position = self._synced_position()
        bill = self._posted_bill(position)
        refund = self._reverse(bill, quantity=30.0)
        refund.action_post()

        today = fields.Date.today()
        adjustments = self.env['petroleum.desk.dashboard']._get_supplier_margin_adjustments({
            'date_from': today,
            'date_to': today,
            'product_id': False,
            'partner_id': False,
            'supplier_id': False,
            'deal_state': '',
        })
        self.assertNotIn(refund, adjustments)

    # ------------------------------------------------------------------
    # Customer side
    # ------------------------------------------------------------------

    def test_customer_partial_reversal_updates_deal(self):
        deal, position = self._confirmed_deal()
        invoice = self._post_customer_invoice(deal)
        line = deal.line_ids
        sale_line = deal.sale_order_id.order_line.filtered(
            lambda so_line: so_line.product_id == line.product_id)
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.state == 'active')

        credit = self._reverse(invoice, quantity=20.0)
        credit.action_post()

        self.assertTrue(credit.petro_qty_propagated)
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(sale_line.product_uom_qty, 80.0)
        self.assertEqual(allocation.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)
        self.assertEqual(deal.total_qty, 80.0)
        # The refund's litres live on the deal line now; it must not also be
        # counted as a sell adjustment (no double reduction).
        self.assertEqual(deal.amount_sell, 800.0)
        self.assertEqual(deal.adjustment_sell_total, 0.0)

    def test_customer_full_reversal_blocked(self):
        deal, _position = self._confirmed_deal()
        invoice = self._post_customer_invoice(deal)

        credit = self._reverse(invoice)  # full 100 L → deal would hit 0
        with self.assertRaises(UserError) as error:
            credit.action_post()
        self.assertIn('deal revision wizard', str(error.exception))

    def test_customer_reversal_reset_to_draft_restores_deal(self):
        deal, position = self._confirmed_deal()
        invoice = self._post_customer_invoice(deal)
        line = deal.line_ids

        credit = self._reverse(invoice, quantity=20.0)
        credit.action_post()
        self.assertEqual(line.quantity, 80.0)

        credit.button_draft()

        self.assertFalse(credit.petro_qty_propagated)
        self.assertEqual(line.quantity, 100.0)
        self.assertEqual(position.qty_remaining, 50.0)

    def test_deal_wizard_credit_note_does_not_propagate(self):
        deal, position = self._confirmed_deal()
        self._post_customer_invoice(deal)
        line = deal.line_ids

        wizard = self.env['petroleum.deal.revise.confirmed'].create({
            'deal_id': deal.id,
            'deal_line_id': line.id,
            'current_quantity': line.quantity,
            'current_sell_price': line.sell_price,
            'new_quantity': 80.0,
            'new_sell_price': 10.0,
            'note': 'Short-loaded',
        })
        action = wizard.action_confirm()
        credit = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(credit.petro_adjustment_quantity, 20.0)
        self.assertEqual(line.quantity, 80.0)

        credit.action_post()

        self.assertFalse(credit.petro_qty_propagated)
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)
