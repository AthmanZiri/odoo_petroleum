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

    def _wizard(self, target=None, restrict=None):
        context = {}
        if restrict is not None:
            context['carry_forward_line_ids'] = restrict.ids
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
        wizard = self._wizard(restrict=current | source)

        self.assertEqual(wizard.line_ids.position_line_id, source)
        wizard.action_confirm()

        self.assertEqual(current.qty_opening, 15.0)
        self.assertFalse(current.rolled_forward_on)
        self.assertEqual(source.rolled_forward_on, self.target)

    def test_selected_rows_carry_only_those_lots(self):
        chosen = self._lot(self.source_date, 40.0, 7.0)
        other = self._lot(self.source_date, 12.0, 9.0)
        action = chosen.action_carry_forward()
        self.assertEqual(action['context']['carry_forward_line_ids'], chosen.ids)

        wizard = self._wizard(restrict=chosen)
        self.assertEqual(wizard.line_ids.position_line_id, chosen)
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
