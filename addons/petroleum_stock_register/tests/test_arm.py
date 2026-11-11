import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestStockRegisterArm(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_a.write({
            'fuel_ok': True,
            'type': 'consu',
            'purchase_ok': True,
            'sale_ok': True,
            'purchase_method': 'purchase',
            'invoice_policy': 'order',
            'is_storable': False,
            'taxes_id': [fields.Command.set([])],
            'supplier_taxes_id': [fields.Command.set([])],
        })
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.env.company.petro_stock_register_mode = 'firewall'
        cls.env.company.inventory_valuation = 'periodic'

    def _deal(self):
        return self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': 1000.0,
                'sell_price': 10.0,
                'buy_price': 8.0,
                'supplier_id': self.partner_b.id,
            })],
        })

    def test_firewall_confirm_clears_track_inventory(self):
        self.product_a.is_storable = True
        self._deal()._prepare_products()
        self.assertFalse(self.product_a.is_storable)
        self.assertEqual(self.product_a.invoice_policy, 'order')
        self.assertEqual(self.product_a.purchase_method, 'purchase')

    def test_arm_keeps_track_inventory_on_prepare(self):
        self.env.company.action_arm_stock_register()
        self.assertEqual(self.env.company.petro_stock_register_mode, 'armed')
        self.assertTrue(self.product_a.is_storable)
        self.product_a.is_storable = False
        self._deal()._prepare_products()
        self.assertTrue(self.product_a.is_storable)
        self.assertEqual(self.product_a.invoice_policy, 'order')

    def test_perpetual_valuation_refuses_to_arm(self):
        self.env.company.inventory_valuation = 'real_time'
        with self.assertRaises(UserError):
            self.env.company.action_arm_stock_register()
        self.assertEqual(self.env.company.petro_stock_register_mode, 'firewall')

    def test_loadings_import_keeps_track_inventory_when_armed(self):
        self.env.company.action_arm_stock_register()
        self.product_a.is_storable = False
        wizard = self.env['petroleum.loadings.import'].create({
            'loadings_file': base64.b64encode(b'unused'),
            'loadings_filename': 'loadings.xlsx',
        })
        wizard._prepare_fuel_products_once({
            'product_cache': {'PMS': self.product_a},
        })
        self.assertTrue(self.product_a.is_storable)

    def test_inventory_closing_skips_fuel(self):
        self.env.company.action_arm_stock_register()
        accounts = self.env.company._get_accounts_by_product()
        self.assertNotIn(self.product_a, accounts)
        self.assertTrue(all(not product.fuel_ok for product in accounts))
