from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestFuelPickingFirewall(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.env.user.group_ids |= cls.env.ref('purchase.group_purchase_manager')
        cls.product_a.write({
            'fuel_ok': True,
            'type': 'consu',
            'purchase_ok': True,
            'sale_ok': True,
            'purchase_method': 'purchase',
            'invoice_policy': 'order',
            'is_storable': True,
            'taxes_id': [fields.Command.set([])],
            'supplier_taxes_id': [fields.Command.set([])],
        })
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.other_product = cls.env['product.product'].create({
            'name': 'Pump spare',
            'type': 'consu',
            'is_storable': True,
            'purchase_ok': True,
            'sale_ok': True,
            'list_price': 15.0,
            'taxes_id': [fields.Command.set([])],
            'supplier_taxes_id': [fields.Command.set([])],
        })

    def test_fuel_sale_has_no_picking_even_when_automation_is_on(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'order_line': [fields.Command.create({
                'product_id': self.product_a.id,
                'product_uom_qty': 4000.0,
                'price_unit': 10.0,
            })],
        })
        order.warehouse_id.write({
            'is_delivery_set_to_done': True,
            'create_invoice': True,
            'validate_invoice': True,
        })
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertFalse(order.picking_ids.filtered(
            lambda picking: picking.state != 'cancel'))
        self.assertFalse(order.invoice_ids)

    def test_non_fuel_sale_still_creates_a_delivery(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'order_line': [fields.Command.create({
                'product_id': self.other_product.id,
                'product_uom_qty': 2.0,
                'price_unit': 15.0,
            })],
        })
        order.warehouse_id.write({
            'is_delivery_set_to_done': False,
            'create_invoice': False,
            'validate_invoice': False,
        })
        order.action_confirm()
        self.assertTrue(order.picking_ids.filtered(
            lambda picking: picking.state != 'cancel'))

    def test_fuel_purchase_has_no_receipt(self):
        purchase = self.env['purchase.order'].create({
            'partner_id': self.partner_b.id,
            'order_line': [fields.Command.create({
                'product_id': self.product_a.id,
                'product_qty': 10000.0,
                'price_unit': 8.0,
            })],
        })
        purchase.button_confirm()
        self.assertEqual(purchase.state, 'purchase')
        self.assertFalse(purchase.picking_ids.filtered(
            lambda picking: picking.state != 'cancel'))

    def test_company_starts_in_firewall_mode(self):
        self.assertEqual(self.env.company.petro_stock_register_mode, 'firewall')
