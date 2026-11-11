from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestRegisterLocations(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_a.write({
            'fuel_ok': True,
            'type': 'consu',
            'is_storable': True,
            'taxes_id': [fields.Command.set([])],
            'supplier_taxes_id': [fields.Command.set([])],
        })
        cls.env.company.inventory_valuation = 'periodic'
        cls.env.company._petro_ensure_register_warehouse()

    def test_sale_keeps_the_operational_warehouse(self):
        register = self.env.company.petro_register_warehouse_id
        self.assertEqual(register.code, 'PSR')
        self.assertEqual(register.sequence, 100)
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'order_line': [fields.Command.create({
                'product_id': self.product_a.id,
                'product_uom_qty': 1.0,
                'price_unit': 1.0,
            })],
        })
        self.assertTrue(order.warehouse_id)
        self.assertNotEqual(order.warehouse_id, register)

    def test_depot_location_follows_name(self):
        depot = self.env['petroleum.depot'].create({'name': 'SOT-REGISTER'})
        location = depot._petro_location(self.env.company)
        self.assertTrue(location)
        self.assertEqual(location.location_id, self.env.company.petro_register_warehouse_id.lot_stock_id)
        depot.name = 'SOT-RENAMED'
        self.assertEqual(location.name, 'SOT-RENAMED')

    def test_duplicate_depot_unlink_keeps_the_keeper_location(self):
        keeper = self.env['petroleum.depot'].create({'name': 'MERGE-REGISTER'})
        duplicate = self.env['petroleum.depot'].with_context(
            skip_depot_name_reuse=True).create({'name': 'MERGE-REGISTER'})
        duplicate_location = duplicate._petro_location(self.env.company)
        self.assertTrue(duplicate_location)
        duplicate.unlink()
        self.assertFalse(duplicate.exists())
        self.assertTrue(keeper._petro_location(self.env.company).active)

    def test_inventory_adjustment_on_a_depot_is_refused(self):
        depot = self.env['petroleum.depot'].create({'name': 'ADJUST-REGISTER'})
        location = depot._petro_location(self.env.company)
        quant = self.env['stock.quant'].create({
            'product_id': self.product_a.id,
            'location_id': location.id,
            'inventory_quantity': 5.0,
        })
        with self.assertRaises(UserError):
            quant._apply_inventory()

    def test_manual_transfer_into_a_depot_is_refused(self):
        depot = self.env['petroleum.depot'].create({'name': 'TRANSFER-REGISTER'})
        warehouse = self.env.company.petro_register_warehouse_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': depot._petro_location(self.env.company).id,
        })
        with self.assertRaises(UserError):
            picking.button_validate()
