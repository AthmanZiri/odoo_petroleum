from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestReviseLotQuantity(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.product_a.write({'fuel_ok': True, 'default_code': 'PMS'})
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.truck = cls.env['truck.management'].create({
            'name': 'KBB 002B',
            'capacity': 200.0,
        })

    def _lot(self, qty_bought=25000.0, buy=202.0):
        return self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': qty_bought,
            'buy_price': buy,
        })

    def _remaining_wizard(self, position, **vals):
        base = {
            'position_line_id': position.id,
            'volume_scope': 'remaining',
            'affected_quantity': position.qty_remaining,
            'new_buy_price': position.buy_price,
            'note': 'Lot correction',
        }
        base.update(vals)
        return self.env['petroleum.daily.position.revise.price'].create(base)

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

    def _sold_wizard(self, position, new_buy_price):
        wizard = self.env['petroleum.daily.position.revise.price'].create({
            'position_line_id': position.id,
            'volume_scope': 'sold',
            'affected_quantity': position.qty_sold,
            'new_buy_price': new_buy_price,
            'note': 'Sold correction',
        })
        wizard._populate_sold_lines()
        return wizard

    # ------------------------------------------------------------------
    # Remaining stock: lot litres corrections
    # ------------------------------------------------------------------

    def test_quantity_increase_drafts_debit_bill(self):
        position = self._lot()
        wizard = self._remaining_wizard(
            position, revise_lot_quantity=True, new_lot_quantity=27000.0)
        action = wizard.action_confirm()

        self.assertEqual(position.qty_bought, 27000.0)
        self.assertEqual(position.qty_remaining, 27000.0)
        self.assertEqual(position.buy_price, 202.0)
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(move.move_type, 'in_invoice')
        self.assertEqual(move.state, 'draft')
        self.assertFalse(move.petro_price_adjustment)
        self.assertEqual(move.petro_adjustment_quantity, 2000.0)
        self.assertEqual(move.invoice_line_ids.quantity, 2000.0)
        self.assertEqual(move.invoice_line_ids.price_unit, 202.0)
        history = position.price_history_ids.filtered(
            lambda h: h.reason == 'quantity_revision')
        self.assertEqual(len(history), 1)
        self.assertEqual(history.old_quantity, 25000.0)
        self.assertEqual(history.new_quantity, 27000.0)

    def test_quantity_decrease_drafts_credit_note(self):
        position = self._lot()
        wizard = self._remaining_wizard(
            position, revise_lot_quantity=True, new_lot_quantity=20000.0)
        action = wizard.action_confirm()

        self.assertEqual(position.qty_bought, 20000.0)
        self.assertEqual(position.qty_remaining, 20000.0)
        move = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(move.move_type, 'in_refund')
        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.invoice_line_ids.quantity, 5000.0)
        self.assertEqual(move.invoice_line_ids.price_unit, 202.0)

    def test_quantity_decrease_without_document(self):
        position = self._lot()
        wizard = self._remaining_wizard(
            position, revise_lot_quantity=True, new_lot_quantity=20000.0,
            create_credit_note=False)
        action = wizard.action_confirm()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(position.qty_remaining, 20000.0)
        self.assertFalse(self.env['account.move'].search([
            ('partner_id', '=', self.partner_b.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
        ]))

    def test_no_change_and_negative_quantity_rejected(self):
        position = self._lot()
        wizard = self._remaining_wizard(
            position, revise_lot_quantity=True,
            new_lot_quantity=position.qty_remaining)
        with self.assertRaises(UserError):
            wizard.action_confirm()

        with self.assertRaises(UserError):
            position.action_revise_lot_quantity(-1.0)

    def test_combined_price_and_quantity_revision(self):
        position = self._lot()
        wizard = self._remaining_wizard(
            position, revise_lot_quantity=True, new_lot_quantity=20000.0,
            new_buy_price=201.0)
        action = wizard.action_confirm()
        moves = self.env['account.move'].search(action['domain'])

        self.assertEqual(len(moves), 2)
        qty_note = moves.filtered(lambda m: not m.petro_price_adjustment)
        price_note = moves.filtered(
            lambda m: m.petro_price_adjustment == 'supplier_buy')
        self.assertEqual(qty_note.move_type, 'in_refund')
        self.assertEqual(qty_note.invoice_line_ids.quantity, 5000.0)
        self.assertEqual(qty_note.invoice_line_ids.price_unit, 202.0)
        self.assertEqual(price_note.move_type, 'in_refund')
        self.assertEqual(price_note.invoice_line_ids.quantity, 20000.0)
        self.assertEqual(price_note.invoice_line_ids.price_unit, 1.0)
        self.assertEqual(position.buy_price, 201.0)
        self.assertEqual(position.qty_remaining, 20000.0)

    def test_price_only_revision_unchanged(self):
        """Regression: default wizard (no quantity correction) behaves as before."""
        position = self._lot()
        wizard = self._remaining_wizard(position, new_buy_price=201.0)
        action = wizard.action_confirm()
        move = self.env['account.move'].browse(action['res_id'])

        self.assertFalse(wizard.revise_lot_quantity)
        self.assertEqual(move.petro_price_adjustment, 'supplier_buy')
        self.assertEqual(move.invoice_line_ids.quantity, 25000.0)
        self.assertEqual(position.buy_price, 201.0)
        self.assertEqual(position.qty_bought, 25000.0)

    # ------------------------------------------------------------------
    # Sold scope: deal litres corrections
    # ------------------------------------------------------------------

    def test_sold_quantity_reduction_credits_customer(self):
        deal, position = self._confirmed_deal()
        invoice = self._post_customer_invoice(deal)
        line = deal.line_ids
        sale_line = deal.sale_order_id.order_line.filtered(
            lambda so_line: so_line.product_id == line.product_id)
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.state == 'active')

        wizard = self._sold_wizard(position, new_buy_price=7.0)
        wizard.line_ids.new_quantity = 80.0
        action = wizard.action_confirm()

        credit = self.env['account.move'].browse(action['res_id'])
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

    def test_sold_quantity_reduction_without_invoice(self):
        deal, position = self._confirmed_deal()
        line = deal.line_ids

        wizard = self._sold_wizard(position, new_buy_price=7.0)
        wizard.line_ids.new_quantity = 80.0
        action = wizard.action_confirm()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)

    def test_sold_quantity_increase_allocates_remaining(self):
        deal, position = self._confirmed_deal()
        self._post_customer_invoice(deal)
        line = deal.line_ids
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.state == 'active')

        wizard = self._sold_wizard(position, new_buy_price=7.0)
        wizard.line_ids.new_quantity = 120.0
        action = wizard.action_confirm()

        debit = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(debit.move_type, 'out_invoice')
        self.assertEqual(debit.invoice_line_ids.quantity, 20.0)
        self.assertEqual(debit.invoice_line_ids.price_unit, 10.0)
        self.assertEqual(line.quantity, 120.0)
        self.assertEqual(allocation.quantity, 120.0)
        self.assertEqual(position.qty_remaining, 30.0)

    def test_sold_quantity_and_price_revision(self):
        deal, position = self._confirmed_deal()
        invoice = self._post_customer_invoice(deal)
        line = deal.line_ids
        allocation = deal.position_allocation_ids.filtered(
            lambda alloc: alloc.state == 'active')

        wizard = self._sold_wizard(position, new_buy_price=6.5)
        wizard.line_ids.new_quantity = 80.0
        action = wizard.action_confirm()
        moves = self.env['account.move'].search(action['domain'])

        self.assertEqual(len(moves), 2)
        customer_credit = moves.filtered(
            lambda m: m.move_type == 'out_refund')
        supplier_credit = moves.filtered(
            lambda m: m.petro_price_adjustment == 'supplier_buy')
        self.assertEqual(customer_credit.invoice_line_ids.quantity, 20.0)
        self.assertEqual(customer_credit.petro_original_move_id, invoice)
        self.assertEqual(supplier_credit.move_type, 'in_refund')
        self.assertEqual(supplier_credit.invoice_line_ids.quantity, 80.0)
        self.assertEqual(supplier_credit.invoice_line_ids.price_unit, 0.5)
        self.assertEqual(supplier_credit.deal_id, deal)
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(allocation.quantity, 80.0)
        self.assertEqual(allocation.buy_price, 6.5)
        self.assertEqual(position.qty_remaining, 70.0)
