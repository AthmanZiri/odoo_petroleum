from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestConfirmedDealRevision(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.product_a.write({'fuel_ok': True, 'default_code': 'PMS'})
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.truck = cls.env['truck.management'].create({
            'name': 'KAA 001A',
            'capacity': 200.0,
        })

    def _confirmed_deal(self):
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
                'quantity': 100.0,
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

    def _wizard(self, deal, new_quantity, new_sell_price, note='Correction'):
        line = deal.line_ids[:1]
        return self.env['petroleum.deal.revise.confirmed'].create({
            'deal_id': deal.id,
            'deal_line_id': line.id,
            'current_quantity': line.quantity,
            'current_sell_price': line.sell_price,
            'new_quantity': new_quantity,
            'new_sell_price': new_sell_price,
            'note': note,
        })

    def test_revise_confirmed_deal_updates_operational_records(self):
        deal, position = self._confirmed_deal()
        line = deal.line_ids
        sale_line = deal.sale_order_id.order_line.filtered(
            lambda order_line: order_line.product_id == line.product_id)
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.deal_line_id == line and alloc.state == 'active')

        self.assertEqual(deal.state, 'confirmed')
        self.assertEqual(sale_line.product_uom_qty, 100.0)
        self.assertEqual(allocation.quantity, 100.0)
        self.assertEqual(position.qty_remaining, 50.0)

        wizard = self.env['petroleum.deal.revise.confirmed'].create({
            'deal_id': deal.id,
            'deal_line_id': line.id,
            'current_quantity': line.quantity,
            'current_sell_price': line.sell_price,
            'new_quantity': 120.0,
            'new_sell_price': 11.0,
            'note': 'Customer increased order before loading',
        })
        wizard.action_confirm()

        self.assertEqual(line.quantity, 120.0)
        self.assertEqual(line.sell_price, 11.0)
        self.assertEqual(sale_line.product_uom_qty, 120.0)
        self.assertEqual(sale_line.price_unit, 11.0)
        self.assertEqual(allocation.quantity, 120.0)
        self.assertEqual(position.qty_remaining, 30.0)
        self.assertEqual(deal.total_qty, 120.0)
        self.assertEqual(deal.amount_sell, 1320.0)

    def test_revise_confirmed_deal_reduces_position_allocation(self):
        deal, position = self._confirmed_deal()
        line = deal.line_ids
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.deal_line_id == line and alloc.state == 'active')

        self._wizard(deal, 80.0, 9.5, 'Customer reduced order before loading').action_confirm()

        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(line.sell_price, 9.5)
        self.assertEqual(allocation.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)

    def test_revise_invoiced_deal_qty_reduction_creates_credit_note(self):
        deal, position = self._confirmed_deal()
        line = deal.line_ids
        invoice = self._post_customer_invoice(deal)
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.deal_line_id == line and alloc.state == 'active')
        sale_line = deal.sale_order_id.order_line.filtered(
            lambda order_line: order_line.product_id == line.product_id)

        action = self._wizard(deal, 80.0, 10.0, 'Short-loaded').action_confirm()
        credit = self.env['account.move'].browse(action['res_id'])

        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(credit.move_type, 'out_refund')
        self.assertEqual(credit.state, 'draft')
        self.assertFalse(credit.petro_price_adjustment)
        self.assertEqual(credit.petro_original_move_id, invoice)
        self.assertEqual(credit.invoice_line_ids.quantity, 20.0)
        self.assertEqual(credit.invoice_line_ids.price_unit, 10.0)
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(sale_line.product_uom_qty, 80.0)
        self.assertEqual(allocation.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)

    def test_revise_invoiced_deal_price_only_creates_price_adjustment(self):
        deal, position = self._confirmed_deal()
        line = deal.line_ids
        invoice = self._post_customer_invoice(deal)

        action = self._wizard(deal, 100.0, 11.0, 'Price increase').action_confirm()
        debit = self.env['account.move'].browse(action['res_id'])

        self.assertEqual(debit.move_type, 'out_invoice')
        self.assertEqual(debit.state, 'draft')
        self.assertEqual(debit.petro_price_adjustment, 'customer_sell')
        self.assertEqual(debit.petro_original_move_id, invoice)
        self.assertEqual(debit.petro_old_price, 10.0)
        self.assertEqual(debit.petro_new_price, 11.0)
        self.assertEqual(debit.petro_adjustment_quantity, 100.0)
        self.assertEqual(debit.invoice_line_ids.quantity, 100.0)
        self.assertEqual(debit.invoice_line_ids.price_unit, 1.0)
        self.assertEqual(line.sell_price, 11.0)
        self.assertEqual(position.qty_remaining, 50.0)

    def test_revise_invoiced_deal_qty_and_price_creates_two_drafts(self):
        deal, position = self._confirmed_deal()
        line = deal.line_ids
        invoice = self._post_customer_invoice(deal)
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.deal_line_id == line and alloc.state == 'active')

        action = self._wizard(deal, 80.0, 9.0, 'Qty and price').action_confirm()
        drafts = self.env['account.move'].search(action['domain'])

        self.assertEqual(action['view_mode'], 'list,form')
        self.assertEqual(len(drafts), 2)
        qty_note = drafts.filtered(lambda move: not move.petro_price_adjustment)
        price_note = drafts.filtered(
            lambda move: move.petro_price_adjustment == 'customer_sell')
        self.assertEqual(len(qty_note), 1)
        self.assertEqual(len(price_note), 1)
        self.assertEqual(qty_note.move_type, 'out_refund')
        self.assertEqual(qty_note.invoice_line_ids.quantity, 20.0)
        self.assertEqual(qty_note.invoice_line_ids.price_unit, 10.0)
        self.assertEqual(price_note.move_type, 'out_refund')
        self.assertEqual(price_note.invoice_line_ids.quantity, 80.0)
        self.assertEqual(price_note.invoice_line_ids.price_unit, 1.0)
        self.assertEqual(price_note.petro_original_move_id, invoice)
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(line.sell_price, 9.0)
        self.assertEqual(allocation.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)

    def test_revise_confirmed_deal_blocks_draft_invoice(self):
        deal, _position = self._confirmed_deal()
        invoices = deal.sale_order_id._create_invoices()
        self.assertEqual(invoices.state, 'draft')
        self.assertFalse(deal.invoice_ids.filtered(lambda m: m.state == 'posted'))

        with self.assertRaises(UserError) as error:
            self._wizard(deal, 80.0, 10.0).action_confirm()
        self.assertIn('draft invoice', str(error.exception).lower())

    def test_revise_loaded_deal_qty_and_price(self):
        deal, position = self._confirmed_deal()
        line = deal.line_ids
        invoice = self._post_customer_invoice(deal)
        deal.write({'state': 'loaded'})
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.deal_line_id == line and alloc.state == 'active')

        action = deal.action_open_revise_confirmed()
        self.assertEqual(action['res_model'], 'petroleum.deal.revise.confirmed')

        action = self._wizard(deal, 80.0, 9.0, 'Loaded short + price').action_confirm()
        drafts = self.env['account.move'].search(action['domain'])

        self.assertEqual(len(drafts), 2)
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(line.sell_price, 9.0)
        self.assertEqual(allocation.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)
        self.assertTrue(
            drafts.filtered(lambda move: move.petro_original_move_id == invoice))

    def test_revise_sell_price_button_opens_unified_wizard(self):
        deal, _position = self._confirmed_deal()
        self._post_customer_invoice(deal)
        deal.write({'state': 'loaded'})
        action = deal.action_open_revise_sell_price()
        self.assertEqual(action['res_model'], 'petroleum.deal.revise.confirmed')
