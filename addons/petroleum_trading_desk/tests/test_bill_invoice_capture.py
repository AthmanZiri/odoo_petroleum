from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestBillInvoiceCapture(AccountTestInvoicingCommon):

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
            'name': 'KDD 004D',
            'capacity': 200.0,
        })
        cls.Position = cls.env['petroleum.daily.position.line']

    def _manual_bill(self, qty=5000.0, price=200.0):
        return self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_b.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': qty,
                'price_unit': price,
                'tax_ids': [fields.Command.set([])],
            })],
        })

    def _manual_invoice(self, deal=None, qty=100.0, price=10.0, buy=0.0):
        vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': qty,
                'price_unit': price,
                'petro_buy_price': buy,
                'tax_ids': [fields.Command.set([])],
            })],
        }
        if deal:
            vals['deal_id'] = deal.id
        return self.env['account.move'].create(vals)

    def _confirmed_deal(self, quantity=100.0):
        position = self.Position.create({
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

    # ------------------------------------------------------------------
    # Vendor bill capture
    # ------------------------------------------------------------------

    def test_manual_vendor_bill_creates_lot(self):
        bill = self._manual_bill()
        bill.action_post()

        self.assertTrue(bill.petro_qty_propagated)
        lot = self.Position.search([('created_from_move_id', '=', bill.id)])
        self.assertEqual(len(lot), 1)
        self.assertEqual(lot.date, fields.Date.today())
        self.assertEqual(lot.supplier_id, self.partner_b)
        self.assertEqual(lot.buy_price, 200.0)
        self.assertEqual(lot.qty_bought, 5000.0)
        self.assertEqual(lot.qty_remaining, 5000.0)
        self.assertTrue(lot.price_history_ids.filtered(
            lambda h: h.reason == 'quantity_revision'))

    def test_manual_vendor_bill_matching_board_lot_no_double(self):
        board_lot = self.Position.create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 5000.0,
            'buy_price': 200.0,
        })
        bill = self._manual_bill()
        bill.action_post()

        self.assertFalse(bill.petro_qty_propagated)
        self.assertEqual(board_lot.qty_bought, 5000.0)
        self.assertFalse(
            self.Position.search([('created_from_move_id', '=', bill.id)]))

    def test_vendor_bill_reset_and_repost(self):
        bill = self._manual_bill()
        bill.action_post()
        lot = self.Position.search([('created_from_move_id', '=', bill.id)])

        bill.button_draft()
        self.assertFalse(bill.petro_qty_propagated)
        self.assertEqual(lot.qty_remaining, 0.0)

        bill.action_post()
        self.assertTrue(bill.petro_qty_propagated)
        self.assertEqual(lot.qty_bought, 5000.0)
        self.assertEqual(lot.qty_remaining, 5000.0)
        # Re-post reuses the original lot instead of creating a twin.
        self.assertEqual(
            self.Position.search_count(
                [('created_from_move_id', '=', bill.id)]), 1)

    def test_vendor_bill_reset_blocked_when_sold(self):
        bill = self._manual_bill()
        bill.action_post()
        lot = self.Position.search([('created_from_move_id', '=', bill.id)])
        deal = self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': 3000.0,
                'sell_price': 210.0,
                'buy_price': 200.0,
                'supplier_id': self.partner_b.id,
            })],
        })
        self.env['petroleum.daily.position.allocation'].create({
            'position_line_id': lot.id,
            'deal_id': deal.id,
            'deal_line_id': deal.line_ids.id,
            'quantity': 3000.0,
            'buy_price': 200.0,
        })

        with self.assertRaises(UserError) as error:
            bill.button_draft()
        self.assertIn('remain unsold', str(error.exception))

    def test_synced_bill_not_captured(self):
        position = self.Position.create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 100.0,
            'buy_price': 10.0,
        })
        position._sync_purchase_order_line()
        bill = position.purchase_order_id._daily_position_quantity_bills().filtered(
            lambda move: move.state == 'posted'
            and move.move_type == 'in_invoice')

        self.assertEqual(len(bill), 1)
        self.assertFalse(bill.petro_qty_propagated)
        self.assertEqual(position.qty_bought, 100.0)
        self.assertEqual(self.Position.search_count([
            ('product_id', '=', self.product_a.id),
            ('supplier_id', '=', self.partner_b.id),
        ]), 1)

    # ------------------------------------------------------------------
    # Customer invoice vs deal reconciliation
    # ------------------------------------------------------------------

    def test_customer_invoice_matching_deal_posts(self):
        deal, _position = self._confirmed_deal()
        invoice = self._manual_invoice(deal=deal, qty=100.0, price=10.0, buy=7.0)
        invoice.action_post()

        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(deal.line_ids.quantity, 100.0)
        self.assertFalse(invoice.petro_needs_desk_link)

    def test_customer_invoice_qty_conflict_blocked(self):
        deal, _position = self._confirmed_deal()
        invoice = self._manual_invoice(deal=deal, qty=120.0, price=10.0)

        with self.assertRaises(UserError) as error:
            invoice.action_post()
        self.assertIn('revision wizard', str(error.exception))
        self.assertEqual(deal.line_ids.quantity, 100.0)

    def test_customer_invoice_price_conflict_blocked(self):
        deal, _position = self._confirmed_deal()
        invoice = self._manual_invoice(deal=deal, qty=100.0, price=11.0)

        with self.assertRaises(UserError) as error:
            invoice.action_post()
        self.assertIn('sell price', str(error.exception))

    def test_deal_generated_invoice_not_blocked(self):
        deal, _position = self._confirmed_deal()
        invoices = deal.sale_order_id._create_invoices()
        invoices.write({
            'deal_id': deal.id,
            'invoice_date': fields.Date.today(),
        })
        invoices.action_post()
        self.assertEqual(invoices.state, 'posted')
        self.assertFalse(invoices.petro_needs_desk_link)

    # ------------------------------------------------------------------
    # Needs desk link surface
    # ------------------------------------------------------------------

    def test_unlinked_customer_invoice_flagged(self):
        invoice = self._manual_invoice()
        invoice.action_post()

        self.assertEqual(invoice.state, 'posted')
        self.assertTrue(invoice.petro_needs_desk_link)
        self.assertIn('not linked to a trading deal',
                      invoice.petro_desk_link_warning)

    def test_missing_buy_price_flagged_even_with_deal(self):
        deal, _position = self._confirmed_deal()
        invoice = self._manual_invoice(deal=deal, qty=100.0, price=10.0)
        # Not posted (would be qty/price-consistent anyway); the flag must
        # already warn in draft that margin data is missing.
        self.assertTrue(invoice.petro_needs_desk_link)
        self.assertIn('Buy price is missing', invoice.petro_desk_link_warning)

        invoice.invoice_line_ids.petro_buy_price = 7.0
        self.assertFalse(invoice.petro_needs_desk_link)
