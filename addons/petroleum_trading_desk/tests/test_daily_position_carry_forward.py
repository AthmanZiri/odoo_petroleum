from odoo import fields
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
