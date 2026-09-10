from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestDealConfirmPosition(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.product_a.write({
            'fuel_ok': True,
            'default_code': 'PMS',
            'purchase_ok': True,
            'purchase_method': 'purchase',
            'is_storable': False,
        })
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.truck = cls.env['truck.management'].create({
            'name': 'KAA 1162A',
            'capacity': 12000.0,
        })
        cls.depot_kprl = cls.env['petroleum.depot'].create({'name': 'KPRL-TEST'})
        cls.depot_kprl_dup = cls.env['petroleum.depot'].with_context(
            skip_depot_name_reuse=True).create({'name': 'KPRL-TEST'})
        cls.depot_gapco = cls.env['petroleum.depot'].create({'name': 'GAPCO-TEST'})

    def _position(self, depot, qty=11000.0, price=200.0, extra=None):
        vals = {
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'depot_id': depot.id,
            'qty_opening': qty,
            'buy_price': price,
            'sell_price': price + 1.3,
        }
        if extra:
            vals.update(extra)
        return self.env['petroleum.daily.position.line'].create(vals)

    def _deal(self, depot, qty=4000.0, price=200.0, lot=False):
        return self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'date': fields.Date.today(),
            'depot_id': depot.id,
            'truck_id': self.truck.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': qty,
                'sell_price': price + 1.3,
                'buy_price': price,
                'supplier_id': self.partner_b.id,
                'position_line_id': lot.id if lot else False,
            })],
        })

    def test_duplicate_depot_name_still_finds_stock(self):
        """Deal on a second KPRL record must see lots stored on the first."""
        lot = self._position(self.depot_kprl, qty=11000.0, price=200.0)
        deal = self._deal(self.depot_kprl_dup, qty=4000.0, price=200.0)
        line = deal.line_ids
        Position = self.env['petroleum.daily.position.line']
        self.assertIn(lot, Position.candidates_for_deal_line(line))
        self.assertEqual(Position.find_for_deal_line(line), lot)
        self.assertTrue(line._position_lot_still_valid(lot))
        deal._allocate_daily_positions()
        self.assertEqual(line.position_line_id, lot)
        self.assertEqual(lot.qty_remaining, 7000.0)

    def test_confirm_with_duplicate_depot_and_matching_buy_price(self):
        lot = self._position(self.depot_kprl, qty=11000.0, price=200.0)
        self._position(self.depot_kprl, qty=20000.0, price=198.0)
        deal = self._deal(self.depot_kprl_dup, qty=4000.0, price=200.0)
        deal.action_confirm()
        self.assertEqual(deal.state, 'confirmed')
        self.assertEqual(deal.line_ids.position_line_id, lot)
        self.assertEqual(lot.qty_remaining, 7000.0)

    def test_different_depot_name_does_not_match(self):
        self._position(self.depot_kprl, qty=11000.0, price=200.0)
        deal = self._deal(self.depot_gapco, qty=4000.0, price=200.0)
        with self.assertRaises(UserError) as err:
            deal._allocate_daily_positions()
        self.assertIn('Stock for that supplier is recorded at', str(err.exception))
        self.assertIn('KPRL-TEST', str(err.exception))

    def test_creating_same_depot_name_reuses_record(self):
        again = self.env['petroleum.depot'].create({'name': 'kprl-test'})
        self.assertEqual(again, self.depot_kprl)


@tagged('post_install', '-at_install')
class TestDepotDuplicateMerge(AccountTestInvoicingCommon):

    def test_merge_duplicate_depots_retargets_deal(self):
        self.env.user.group_ids |= self.env.ref('sales_team.group_sale_manager')
        self.partner_a.customer_rank = 1
        keeper = self.env['petroleum.depot'].create({'name': 'MERGE-KPRL'})
        duplicate = self.env['petroleum.depot'].with_context(
            skip_depot_name_reuse=True).create({'name': 'MERGE-KPRL'})
        deal = self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'date': fields.Date.today(),
            'depot_id': duplicate.id,
        })
        self.env['petroleum.depot']._merge_duplicate_names()
        self.assertFalse(duplicate.exists())
        self.assertEqual(deal.depot_id, keeper)
