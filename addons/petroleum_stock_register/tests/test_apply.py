from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestStockRegisterApply(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
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
        cls.env.company.inventory_valuation = 'periodic'
        cls.env.company.petro_stock_register_mode = 'firewall'
        cls.depot = cls.env['petroleum.depot'].create({'name': 'APPLY-DEPOT'})
        cls.truck = cls.env['truck.management'].create({
            'name': 'KAA APPLY',
            'capacity': 20000.0,
        })

    def _on_hand(self, depot=None):
        location = self.env.company._petro_register_location(
            depot if depot is not None else self.depot)
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_a.id),
            ('location_id', '=', location.id),
        ])
        return sum(quants.mapped('quantity'))

    def _moves(self):
        return self.env['stock.move'].search([
            ('petro_register', '=', True),
            ('product_id', '=', self.product_a.id),
            ('state', '=', 'done'),
        ])

    def test_opening_confirm_carry_and_repair(self):
        self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'depot_id': self.depot.id,
            'qty_opening': 10000.0,
            'buy_price': 100.0,
            'sell_price': 110.0,
        })
        self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_opening': 500.0,
            'buy_price': 90.0,
            'sell_price': 100.0,
        })
        opener = self.env['petroleum.stock.register.open'].create({
            'company_id': self.env.company.id,
        })
        opener.action_open()
        self.assertEqual(self.env.company.petro_stock_register_mode, 'live')
        self.assertEqual(self._on_hand(), 10000.0)
        no_depot = self.env.company._petro_register_location(self.env['petroleum.depot'])
        loose = self.env['stock.quant'].search([
            ('product_id', '=', self.product_a.id),
            ('location_id', '=', no_depot.id),
        ])
        self.assertEqual(sum(loose.mapped('quantity')), 500.0)
        with self.assertRaises(UserError):
            opener.action_open()

        deal = self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'date': fields.Date.today(),
            'depot_id': self.depot.id,
            'truck_id': self.truck.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': 4000.0,
                'sell_price': 110.0,
                'buy_price': 100.0,
                'supplier_id': self.partner_b.id,
            })],
        })
        deal.action_confirm()
        self.assertFalse(deal.sale_order_id.picking_ids.filtered(
            lambda picking: picking.state != 'cancel'))
        self.env['petroleum.stock.register']._apply_company(self.env.company.id)
        self.assertEqual(self._on_hand(), 6000.0)
        move_count = len(self._moves())
        self.env['petroleum.stock.register']._apply_company(self.env.company.id)
        self.assertEqual(len(self._moves()), move_count)

        self.env['petroleum.daily.position.line']._carry_forward_to(
            fields.Date.today() + timedelta(days=1))
        self.env['petroleum.stock.register']._apply_company(self.env.company.id)
        self.assertEqual(self._on_hand(), 6000.0)

        location = self.env.company._petro_register_location(self.depot)
        self.env['stock.quant']._update_available_quantity(
            self.product_a, location, -250.0)
        self.assertEqual(self._on_hand(), 5750.0)
        self.env['petroleum.stock.register.hint']._cron_repair()
        self.assertEqual(self._on_hand(), 6000.0)
        self.assertTrue(self.env['petroleum.stock.register.variance'].search([
            ('product_id', '=', self.product_a.id),
            ('depot_id', '=', self.depot.id),
        ]))

    def test_reverse_clears_on_hand_and_returns_to_armed(self):
        self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'depot_id': self.depot.id,
            'qty_opening': 1000.0,
            'buy_price': 100.0,
            'sell_price': 110.0,
        })
        self.env['petroleum.stock.register.open'].create({
            'company_id': self.env.company.id,
        }).action_open()
        self.assertEqual(self._on_hand(), 1000.0)
        self.env['petroleum.stock.register.reverse'].create({
            'company_id': self.env.company.id,
        }).action_reverse()
        self.assertEqual(self.env.company.petro_stock_register_mode, 'armed')
        self.assertFalse(self.env.company.petro_stock_register_open_date)
        self.assertEqual(self._on_hand(), 0.0)
