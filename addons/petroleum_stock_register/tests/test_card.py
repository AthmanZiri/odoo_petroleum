from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestDepotStockCard(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_a.write({
            'fuel_ok': True,
            'type': 'consu',
            'is_storable': False,
            'purchase_method': 'purchase',
            'invoice_policy': 'order',
            'taxes_id': [fields.Command.set([])],
            'supplier_taxes_id': [fields.Command.set([])],
        })
        cls.partner_b.supplier_rank = 1
        cls.env.company.inventory_valuation = 'periodic'
        cls.env.company.petro_stock_register_mode = 'firewall'
        cls.depot = cls.env['petroleum.depot'].create({'name': 'CARD-DEPOT'})

    def test_card_closing_matches_unrolled_remaining(self):
        self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'depot_id': self.depot.id,
            'qty_opening': 2500.0,
            'buy_price': 80.0,
            'sell_price': 90.0,
        })
        self.env['petroleum.stock.register.open'].create({
            'company_id': self.env.company.id,
        }).action_open()
        card = self.env['petroleum.stock.register.card'].create({
            'company_id': self.env.company.id,
            'product_id': self.product_a.id,
            'depot_id': self.depot.id,
            'date_from': fields.Date.today(),
            'date_to': fields.Date.today(),
        })
        card.action_build()
        self.assertTrue(card.line_ids)
        self.assertEqual(card.line_ids[-1].balance, 2500.0)
        self.assertEqual(card.line_ids[-1].origin, 'Opening balance')
