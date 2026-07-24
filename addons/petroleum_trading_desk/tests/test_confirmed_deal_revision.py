from odoo import fields
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

        wizard = self.env['petroleum.deal.revise.confirmed'].create({
            'deal_id': deal.id,
            'deal_line_id': line.id,
            'current_quantity': line.quantity,
            'current_sell_price': line.sell_price,
            'new_quantity': 80.0,
            'new_sell_price': 9.5,
            'note': 'Customer reduced order before loading',
        })
        wizard.action_confirm()

        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(line.sell_price, 9.5)
        self.assertEqual(allocation.quantity, 80.0)
        self.assertEqual(position.qty_remaining, 70.0)
