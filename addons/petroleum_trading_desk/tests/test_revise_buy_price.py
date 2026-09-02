from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestReviseBuyPrice(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.env.user.group_ids |= cls.env.ref('purchase.group_purchase_manager')
        cls.product_a.write({
            'fuel_ok': True,
            'default_code': 'PMS',
            'purchase_ok': True,
            'purchase_method': 'purchase',
        })
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.partner_c = cls.env['res.partner'].create({
            'name': 'DARUSALAAM',
            'customer_rank': 1,
        })
        cls.partner_d = cls.env['res.partner'].create({
            'name': 'ZAYNU',
            'customer_rank': 1,
        })

    def _deal(self, partner, qty, buy=202.0):
        return self.env['petroleum.deal'].create({
            'partner_id': partner.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': qty,
                'sell_price': 210.0,
                'buy_price': buy,
                'supplier_id': self.partner_b.id,
            })],
        })

    def _lot_with_sold_deals(self):
        """102k sold as 27k + 50k + 25k, with 25k remaining — the Vitalac example."""
        position = self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 127000.0,
            'buy_price': 202.0,
        })
        specs = (
            (self.partner_a, 27000.0),
            (self.partner_c, 50000.0),
            (self.partner_d, 25000.0),
        )
        deals = self.env['petroleum.deal']
        for partner, qty in specs:
            deal = self._deal(partner, qty)
            self.env['petroleum.daily.position.allocation'].create({
                'position_line_id': position.id,
                'deal_id': deal.id,
                'deal_line_id': deal.line_ids.id,
                'quantity': qty,
                'buy_price': 202.0,
            })
            deals |= deal
        return position, deals

    def test_recommend_75000_picks_complete_50k_and_25k_deals(self):
        position, deals = self._lot_with_sold_deals()
        deal_27, deal_50, deal_25 = deals[0], deals[1], deals[2]
        allocations = position.allocation_ids.filtered(
            lambda allocation: allocation.state == 'active')
        pairs = position._recommend_sold_allocation_quantities(
            allocations, 75000.0)
        chosen = {(alloc.deal_id, qty) for alloc, qty in pairs}
        self.assertEqual(chosen, {(deal_50, 50000.0), (deal_25, 25000.0)})
        self.assertNotIn(deal_27, {alloc.deal_id for alloc, _qty in pairs})

    def test_sold_revision_75000_does_not_cut_the_earliest_deal(self):
        position, deals = self._lot_with_sold_deals()
        deal_27, deal_50, deal_25 = deals[0], deals[1], deals[2]
        moves = position.action_create_sold_price_adjustments(
            new_buy_price=201.0, quantity=75000.0, note='Complete deals')
        self.assertEqual(len(moves), 2)
        by_deal = {
            alloc.deal_id: (alloc.quantity, alloc.buy_price)
            for alloc in position.allocation_ids.filtered(
                lambda allocation: allocation.state == 'active')
        }
        self.assertEqual(by_deal[deal_27], (27000.0, 202.0))
        self.assertEqual(by_deal[deal_50], (50000.0, 201.0))
        self.assertEqual(by_deal[deal_25], (25000.0, 201.0))

    def test_sold_revision_all_three_deals(self):
        position, deals = self._lot_with_sold_deals()
        position.action_create_sold_price_adjustments(
            new_buy_price=200.0, quantity=102000.0, note='All sold')
        self.assertEqual(set(position.allocation_ids.mapped('buy_price')), {200.0})
        self.assertEqual(len(deals), 3)

    def test_sold_revision_last_resort_splits_one_deal(self):
        position, deals = self._lot_with_sold_deals()
        deal_27, deal_50, deal_25 = deals[0], deals[1], deals[2]
        # 80k has no exact complete-deal match. Closest complete under 80k is
        # 27k+50k=77k, then 3k split from the remaining 25k deal.
        pairs = position._recommend_sold_allocation_quantities(
            position.allocation_ids, 80000.0)
        by_deal = {alloc.deal_id: qty for alloc, qty in pairs}
        self.assertEqual(by_deal[deal_27], 27000.0)
        self.assertEqual(by_deal[deal_50], 50000.0)
        self.assertEqual(by_deal[deal_25], 3000.0)

    def test_wizard_sold_affected_litres_selects_complete_deals(self):
        position, deals = self._lot_with_sold_deals()
        deal_50, deal_25 = deals[1], deals[2]
        wizard = self.env['petroleum.daily.position.revise.price'].create({
            'position_line_id': position.id,
            'volume_scope': 'sold',
            'affected_quantity': 102000.0,
            'new_buy_price': 201.0,
            'note': 'Supplier price reduction',
        })
        wizard._populate_sold_lines()
        wizard.affected_quantity = 75000.0
        wizard._apply_sold_recommendation()
        selected = wizard.line_ids.filtered('selected')
        self.assertEqual(set(selected.mapped('deal_id')), {deal_50, deal_25})
        self.assertEqual(sum(selected.mapped('affected_quantity')), 75000.0)
        self.assertTrue(all(
            not line.is_split for line in selected))

        moves = wizard.action_confirm()
        self.assertEqual(moves['res_model'], 'account.move')
        by_deal = {
            alloc.deal_id: alloc.buy_price
            for alloc in position.allocation_ids
        }
        self.assertEqual(by_deal[deals[0]], 202.0)
        self.assertEqual(by_deal[deal_50], 201.0)
        self.assertEqual(by_deal[deal_25], 201.0)

    def test_partial_remaining_keeps_unrevised_litres_at_old_price(self):
        position, _deals = self._lot_with_sold_deals()
        self.assertEqual(position.qty_remaining, 25000.0)
        result = position.action_revise_buy_price(
            new_buy_price=201.0,
            note='Partial remaining',
            create_credit_note=False,
            affected_quantity=10000.0,
        )
        new_lot = result['surviving_line']
        self.assertNotEqual(new_lot, position)
        self.assertEqual(position.buy_price, 202.0)
        self.assertEqual(position.qty_remaining, 15000.0)
        self.assertEqual(position.qty_sold, 102000.0)
        self.assertEqual(new_lot.buy_price, 201.0)
        self.assertEqual(new_lot.qty_remaining, 10000.0)
        self.assertEqual(new_lot.qty_sold, 0.0)
        self.assertEqual(
            position.qty_bought + new_lot.qty_bought
            + position.qty_opening + new_lot.qty_opening,
            127000.0,
        )
        self.assertEqual(result['transferred_qty'], 10000.0)

    def test_wizard_remaining_allows_quantity_below_remaining(self):
        position, _deals = self._lot_with_sold_deals()
        wizard = self.env['petroleum.daily.position.revise.price'].create({
            'position_line_id': position.id,
            'volume_scope': 'remaining',
            'affected_quantity': 10000.0,
            'new_buy_price': 201.0,
            'create_credit_note': False,
            'note': 'Supplier price reduction on remaining stock',
        })
        wizard.action_confirm()
        self.assertEqual(position.buy_price, 202.0)
        self.assertEqual(position.qty_remaining, 15000.0)
        new_lot = self.env['petroleum.daily.position.line'].search([
            ('date', '=', position.date),
            ('product_id', '=', position.product_id.id),
            ('supplier_id', '=', position.supplier_id.id),
            ('id', '!=', position.id),
        ])
        self.assertEqual(len(new_lot), 1)
        self.assertEqual(new_lot.buy_price, 201.0)
        self.assertEqual(new_lot.qty_remaining, 10000.0)

    def test_full_remaining_revision_still_updates_the_same_lot(self):
        position = self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 25000.0,
            'buy_price': 202.0,
        })
        result = position.action_revise_buy_price(
            new_buy_price=201.0,
            note='Full remaining',
            create_credit_note=False,
        )
        self.assertEqual(result['surviving_line'], position)
        self.assertEqual(position.buy_price, 201.0)
        self.assertEqual(position.qty_remaining, 25000.0)

    def test_remaining_above_available_still_rejected(self):
        position, _deals = self._lot_with_sold_deals()
        with self.assertRaises(UserError):
            position.action_revise_buy_price(
                new_buy_price=201.0,
                create_credit_note=False,
                affected_quantity=25001.0,
            )
