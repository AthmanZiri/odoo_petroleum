from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestDailyPositionCarryForward(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.product_a.write({'fuel_ok': True, 'default_code': 'PMS'})
        cls.partner_b.supplier_rank = 1
        cls.target = fields.Date.add(fields.Date.today(), days=5)
        cls.source_date = fields.Date.add(cls.target, days=-2)

    def _lot(self, date, qty, price, supplier=None):
        return self.env['petroleum.daily.position.line'].create({
            'date': date,
            'product_id': self.product_a.id,
            'supplier_id': (supplier or self.partner_b).id,
            'qty_opening': qty,
            'buy_price': price,
            'sell_price': price + 3.0,
        })

    def test_carry_forward_uses_the_chosen_date(self):
        source = self._lot(self.source_date, 40.0, 7.0)
        action = self.env['petroleum.daily.position.line'].action_carry_forward()
        self.assertEqual(
            action['res_model'], 'petroleum.daily.position.carry.forward')

        wizard = self.env['petroleum.daily.position.carry.forward'].create({
            'target_date': self.target,
        })
        result = wizard.action_confirm()

        rolled = self.env['petroleum.daily.position.line'].search([
            ('date', '=', self.target),
            ('product_id', '=', self.product_a.id),
            ('rolled_from_line_id', '=', source.id),
        ])
        self.assertEqual(len(rolled), 1)
        self.assertEqual(rolled.qty_opening, 40.0)
        self.assertEqual(source.qty_opening, 40.0)
        self.assertEqual(source.rolled_forward_on, self.target)
        self.assertNotEqual(rolled.date, fields.Date.today())
        self.assertIn(fields.Date.to_string(self.target), result['params']['message'])

        wizard.action_confirm()
        self.assertEqual(source.rolled_forward_on, self.target)
        self.assertEqual(rolled.qty_opening, 40.0)
        self.assertEqual(self.env['petroleum.daily.position.line'].search_count([
            ('date', '=', self.target),
            ('product_id', '=', self.product_a.id),
            ('supplier_id', '=', self.partner_b.id),
            ('buy_price', '=', 7.0),
        ]), 1)

    def test_lot_already_on_the_target_date_is_left_alone(self):
        untouched = self._lot(self.target, 15.0, 9.0)
        source = self._lot(self.source_date, 20.0, 7.0)

        self.env['petroleum.daily.position.line']._carry_forward_to(self.target)

        self.assertEqual(untouched.qty_opening, 15.0)
        self.assertFalse(untouched.rolled_forward_on)
        self.assertEqual(untouched.date, self.target)
        self.assertEqual(source.rolled_forward_on, self.target)

    def test_same_price_lot_on_the_target_date_absorbs_opening(self):
        source = self._lot(self.source_date, 40.0, 7.0)
        existing = self._lot(self.target, 10.0, 7.0)

        self.env['petroleum.daily.position.line']._carry_forward_to(self.target)

        self.assertEqual(existing.qty_opening, 50.0)
        self.assertEqual(source.rolled_forward_on, self.target)
        self.assertFalse(source.rolled_from_line_id)
        self.assertEqual(self.env['petroleum.daily.position.line'].search_count([
            ('date', '=', self.target),
            ('product_id', '=', self.product_a.id),
            ('supplier_id', '=', self.partner_b.id),
        ]), 1)

    def _wizard(self, target=None, source_lines=None):
        context = {}
        if source_lines is not None:
            context['carry_forward_line_ids'] = source_lines.ids
        return self.env['petroleum.daily.position.carry.forward'].with_context(
            **context).create({
                'target_date': target or self.target,
            })

    def test_partial_quantity_leaves_the_leftover(self):
        source = self._lot(self.source_date, 40.0, 7.0)
        wizard = self._wizard()
        self.assertEqual(wizard.line_ids.quantity, 40.0)
        wizard.line_ids.quantity = 15.0

        wizard.action_confirm()

        rolled = self.env['petroleum.daily.position.line'].search([
            ('date', '=', self.target),
            ('rolled_from_line_id', '=', source.id),
        ])
        self.assertEqual(rolled.qty_opening, 15.0)
        self.assertEqual(source.qty_opening, 25.0)
        self.assertEqual(source.qty_remaining, 25.0)
        self.assertFalse(source.rolled_forward_on)
        history = rolled.price_history_ids.filtered(
            lambda row: row.reason == 'roll_forward')
        self.assertIn('15', history[:1].note or '')

        leftover = self._wizard()
        self.assertEqual(leftover.line_ids.position_line_id, source)
        self.assertEqual(leftover.line_ids.quantity, 25.0)
        leftover.action_confirm()
        self.assertEqual(source.rolled_forward_on, self.target)
        self.assertEqual(source.qty_opening, 25.0)
        self.assertEqual(rolled.qty_opening, 40.0)

    def test_partial_peels_opening_then_bought(self):
        source = self._lot(self.source_date, 10.0, 7.0)
        source.write({'qty_bought': 30.0})
        wizard = self._wizard()
        wizard.line_ids.quantity = 25.0

        wizard.action_confirm()

        self.assertEqual(source.qty_opening, 0.0)
        self.assertEqual(source.qty_bought, 15.0)
        self.assertEqual(source.qty_remaining, 15.0)
        self.assertFalse(source.rolled_forward_on)
        rolled = self.env['petroleum.daily.position.line'].search([
            ('date', '=', self.target),
            ('rolled_from_line_id', '=', source.id),
        ])
        self.assertEqual(rolled.qty_opening, 25.0)

    def test_same_price_lot_absorbs_partial_quantity(self):
        source = self._lot(self.source_date, 40.0, 7.0)
        existing = self._lot(self.target, 10.0, 7.0)
        wizard = self._wizard()
        wizard.line_ids.quantity = 12.0

        wizard.action_confirm()

        self.assertEqual(existing.qty_opening, 22.0)
        self.assertEqual(source.qty_opening, 28.0)
        self.assertFalse(source.rolled_forward_on)
        self.assertEqual(self.env['petroleum.daily.position.line'].search_count([
            ('date', '=', self.target),
            ('product_id', '=', self.product_a.id),
            ('supplier_id', '=', self.partner_b.id),
        ]), 1)

    def test_quantity_above_remaining_writes_nothing(self):
        source = self._lot(self.source_date, 40.0, 7.0)
        other = self._lot(self.source_date, 10.0, 9.0)
        wizard = self._wizard()
        wizard.line_ids.filtered(
            lambda line: line.position_line_id == source).quantity = 41.0

        with self.assertRaises(UserError):
            wizard.action_confirm()

        self.assertEqual(source.qty_opening, 40.0)
        self.assertEqual(other.qty_opening, 10.0)
        self.assertFalse(source.rolled_forward_on)
        self.assertFalse(other.rolled_forward_on)
        self.assertFalse(self.env['petroleum.daily.position.line'].search([
            ('date', '=', self.target),
            ('product_id', '=', self.product_a.id),
        ]))

    def test_zero_quantity_skips_the_lot(self):
        skipped = self._lot(self.source_date, 40.0, 7.0)
        kept = self._lot(self.source_date, 10.0, 9.0)
        wizard = self._wizard()
        wizard.line_ids.filtered(
            lambda line: line.position_line_id == skipped).quantity = 0.0

        wizard.action_confirm()

        self.assertFalse(skipped.rolled_forward_on)
        self.assertEqual(skipped.qty_opening, 40.0)
        self.assertEqual(kept.rolled_forward_on, self.target)
        rolled = self.env['petroleum.daily.position.line'].search([
            ('date', '=', self.target),
            ('rolled_from_line_id', '=', kept.id),
        ])
        self.assertEqual(rolled.qty_opening, 10.0)

    def test_lot_on_target_date_is_not_offered(self):
        current = self._lot(self.target, 15.0, 9.0)
        source = self._lot(self.source_date, 20.0, 7.0)
        wizard = self._wizard()

        self.assertEqual(wizard.line_ids.position_line_id, source)
        self.assertEqual(wizard.line_ids.quantity, 20.0)
        self.assertEqual(wizard.line_ids.product_id, source.product_id)
        wizard.action_confirm()

        self.assertEqual(current.qty_opening, 15.0)
        self.assertFalse(current.rolled_forward_on)
        self.assertEqual(source.rolled_forward_on, self.target)

    def test_dialog_lists_every_carryable_lot_with_a_quantity(self):
        chosen = self._lot(self.source_date, 40.0, 7.0)
        other = self._lot(self.source_date, 12.0, 9.0)
        action = self.env['petroleum.daily.position.line'].action_carry_forward()
        self.assertNotIn('carry_forward_line_ids', action['context'])

        wizard = self._wizard()
        self.assertEqual(
            set(wizard.line_ids.mapped('position_line_id').ids),
            {chosen.id, other.id})
        self.assertEqual(
            set(wizard.line_ids.mapped('quantity')), {40.0, 12.0})
        wizard.line_ids.filtered(
            lambda line: line.position_line_id == other).quantity = 0.0
        wizard.action_confirm()

        self.assertEqual(chosen.rolled_forward_on, self.target)
        self.assertFalse(other.rolled_forward_on)
        self.assertEqual(other.qty_remaining, 12.0)

    def test_changing_target_date_reloads_lots(self):
        early = self._lot(self.source_date, 40.0, 7.0)
        day_before = fields.Date.add(self.target, days=-1)
        later = self._lot(day_before, 8.0, 11.0)
        wizard = self._wizard()
        self.assertEqual(
            set(wizard.line_ids.position_line_id.ids), {early.id, later.id})

        wizard.target_date = day_before
        wizard._onchange_target_date()

        self.assertEqual(wizard.line_ids.position_line_id, early)
        self.assertEqual(wizard.line_ids.quantity, 40.0)

    def test_selected_date_does_not_include_a_later_day(self):
        oct12 = self._lot(self.source_date, 40.0, 7.0)
        later_day = fields.Date.add(self.target, days=-1)
        oct14 = self._lot(later_day, 20.0, 9.0)

        action = oct12.action_carry_forward()
        self.assertEqual(action['context']['carry_forward_line_ids'], oct12.ids)
        wizard = self._wizard(source_lines=oct12)

        self.assertEqual(wizard.line_ids.position_line_id, oct12)
        self.assertEqual(wizard.line_ids.quantity, 40.0)
        self.assertNotIn(oct14, wizard.line_ids.position_line_id)

    def test_one_ticked_row_lists_every_lot_on_that_date(self):
        first = self._lot(self.source_date, 40.0, 7.0)
        second = self._lot(self.source_date, 12.0, 9.0)
        later = self._lot(fields.Date.add(self.target, days=-1), 8.0, 11.0)
        wizard = self._wizard(source_lines=first)

        self.assertEqual(
            set(wizard.line_ids.position_line_id.ids), {first.id, second.id})
        self.assertNotIn(later, wizard.line_ids.position_line_id)

    def test_two_selected_dates_exclude_the_rest(self):
        oct9 = self._lot(fields.Date.add(self.source_date, days=-1), 5.0, 4.0)
        oct12 = self._lot(self.source_date, 40.0, 7.0)
        oct14 = self._lot(fields.Date.add(self.target, days=-1), 8.0, 11.0)
        wizard = self._wizard(source_lines=oct9 | oct12)

        self.assertEqual(
            set(wizard.line_ids.position_line_id.ids), {oct9.id, oct12.id})
        self.assertNotIn(oct14, wizard.line_ids.position_line_id)

    def test_already_rolled_date_offers_the_live_lot_not_an_unrelated_day(self):
        oct12 = self._lot(self.source_date, 40.0, 7.0)
        later_day = fields.Date.add(self.target, days=-1)
        unrelated = self._lot(later_day, 20.0, 9.0)
        self.env['petroleum.daily.position.line']._carry_forward_to(later_day)
        live = self.env['petroleum.daily.position.line'].search([
            ('date', '=', later_day),
            ('rolled_from_line_id', '=', oct12.id),
        ])

        wizard = self._wizard(source_lines=oct12)
        self.assertEqual(wizard.line_ids.position_line_id, live)
        self.assertEqual(wizard.line_ids.quantity, 40.0)
        self.assertEqual(wizard.line_ids.date, later_day)
        self.assertIn(fields.Date.to_string(self.source_date), wizard.line_ids.path)
        self.assertIn(fields.Date.to_string(later_day), wizard.line_ids.path)
        self.assertNotIn(unrelated, wizard.line_ids.position_line_id)
        self.assertFalse(wizard.notice)

    def test_selected_date_follows_the_roll_chain_to_the_live_lot(self):
        day12 = fields.Date.add(self.source_date, days=-2)
        day13 = self.source_date
        day14 = fields.Date.add(self.source_date, days=1)
        oct12 = self._lot(day12, 40.0, 7.0)
        Position = self.env['petroleum.daily.position.line']
        Position._carry_forward_to(day13)
        child13 = Position.search([('rolled_from_line_id', '=', oct12.id)])
        child13.qty_bought = 10.0
        Position._carry_forward_to(day14)
        child14 = Position.search([('rolled_from_line_id', '=', child13.id)])

        wizard = self._wizard(source_lines=oct12)
        self.assertEqual(wizard.line_ids.position_line_id, child14)
        self.assertEqual(wizard.line_ids.date, day14)
        self.assertEqual(wizard.line_ids.quantity, 50.0)
        self.assertIn(fields.Date.to_string(day12), wizard.line_ids.path)
        self.assertIn(fields.Date.to_string(day13), wizard.line_ids.path)
        self.assertIn(fields.Date.to_string(day14), wizard.line_ids.path)
        self.assertNotIn('was already carried forward to', wizard.notice or '')

        wizard.action_confirm()
        self.assertEqual(child14.rolled_forward_on, self.target)
        self.assertEqual(oct12.rolled_forward_on, day13)
        self.assertEqual(oct12.qty_remaining, 40.0)
        landed = Position.search([
            ('date', '=', self.target),
            ('rolled_from_line_id', '=', child14.id),
        ])
        self.assertEqual(landed.qty_opening, 50.0)

    def test_partial_carry_peels_the_live_lot_not_the_historical_row(self):
        day12 = fields.Date.add(self.source_date, days=-2)
        day13 = self.source_date
        day14 = fields.Date.add(self.source_date, days=1)
        oct12 = self._lot(day12, 40.0, 7.0)
        Position = self.env['petroleum.daily.position.line']
        Position._carry_forward_to(day13)
        child13 = Position.search([('rolled_from_line_id', '=', oct12.id)])
        Position._carry_forward_to(day14)
        child14 = Position.search([('rolled_from_line_id', '=', child13.id)])

        wizard = self._wizard(source_lines=oct12)
        wizard.line_ids.quantity = 10.0
        wizard.action_confirm()

        self.assertFalse(child14.rolled_forward_on)
        self.assertEqual(child14.qty_remaining, 30.0)
        self.assertEqual(oct12.qty_remaining, 40.0)
        self.assertEqual(oct12.rolled_forward_on, day13)
        landed = Position.search([
            ('date', '=', self.target),
            ('rolled_from_line_id', '=', child14.id),
        ])
        self.assertEqual(landed.qty_opening, 10.0)

    def test_selected_date_with_nothing_left_stays_empty(self):
        dead = self._lot(self.source_date, 0.0, 4.0)
        wizard = self._wizard(source_lines=dead)
        self.assertFalse(wizard.line_ids)
        self.assertIn(fields.Date.to_string(self.source_date), wizard.notice)
        self.assertNotIn(dead, wizard.line_ids.position_line_id)

    def test_chain_already_on_the_destination_is_named_and_omitted(self):
        oct12 = self._lot(self.source_date, 40.0, 7.0)
        self.env['petroleum.daily.position.line']._carry_forward_to(self.target)
        wizard = self._wizard(source_lines=oct12)
        self.assertFalse(wizard.line_ids)
        self.assertIn(oct12.product_id.display_name, wizard.notice)
        self.assertIn(fields.Date.to_string(self.source_date), wizard.notice)
        self.assertIn(fields.Date.to_string(self.target), wizard.notice)
        self.assertNotIn('was already carried forward to', wizard.notice)

    def test_destination_on_the_source_date_does_not_pull_another_day(self):
        oct12 = self._lot(self.source_date, 40.0, 7.0)
        earlier = self._lot(fields.Date.add(self.source_date, days=-2), 6.0, 3.0)
        wizard = self._wizard(source_lines=oct12, target=self.source_date)

        self.assertFalse(wizard.line_ids)
        self.assertNotIn(earlier, wizard.line_ids.position_line_id)
        self.assertIn(fields.Date.to_string(self.source_date), wizard.notice)

        wizard.target_date = fields.Date.add(self.source_date, days=1)
        wizard._onchange_target_date()

        self.assertEqual(wizard.line_ids.position_line_id, oct12)
        self.assertFalse(wizard.notice)
