from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPriceAdjustmentMargin(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.product_a.write({'fuel_ok': True, 'default_code': 'PMS'})
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1
        cls.deal = cls.env['petroleum.deal'].create({
            'partner_id': cls.partner_a.id,
            'line_ids': [fields.Command.create({
                'product_id': cls.product_a.id,
                'quantity': 100.0,
                'sell_price': 10.0,
                'buy_price': 7.0,
                'supplier_id': cls.partner_b.id,
            })],
        })

    @classmethod
    def _create_move(
            cls, move_type, partner, price, buy=0.0, adjustment=False,
            scope='sold'):
        move = cls.env['account.move'].create({
            'move_type': move_type,
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'deal_id': cls.deal.id,
            'petro_price_adjustment': adjustment or False,
            'petro_adjustment_scope': scope if adjustment else False,
            'invoice_line_ids': [cls._prepare_invoice_line(
                product_id=cls.product_a,
                quantity=100.0,
                price_unit=price,
                petro_buy_price=buy,
                tax_ids=cls.env['account.tax'],
            )],
        })
        move.action_post()
        return move

    def _filters(self):
        today = fields.Date.today()
        return {
            'date_from': today,
            'date_to': today,
            'product_id': False,
            'partner_id': False,
            'supplier_id': False,
            'deal_state': '',
        }

    def test_customer_credit_reduces_margin_without_reducing_volume(self):
        invoice = self._create_move(
            'out_invoice', self.partner_a, price=10.0, buy=7.0)
        credit = self._create_move(
            'out_refund', self.partner_a, price=1.0,
            adjustment='customer_sell')

        self.assertEqual(invoice.petro_margin_total, 300.0)
        self.assertEqual(credit.petro_margin_total, -100.0)

        dashboard = self.env['petroleum.desk.dashboard']
        moves = invoice | credit
        self.assertEqual(dashboard._invoice_margin(moves, self._filters()), 200.0)
        sell, volume = dashboard._invoice_sell_and_volume(
            moves, self._filters())
        self.assertEqual(sell, 900.0)
        self.assertEqual(volume['PMS'], 100.0)

    def test_customer_debit_and_supplier_notes_have_correct_signs(self):
        customer_debit = self._create_move(
            'out_invoice', self.partner_a, price=1.0,
            adjustment='customer_sell')
        supplier_credit = self._create_move(
            'in_refund', self.partner_b, price=0.5,
            adjustment='supplier_buy')
        supplier_debit = self._create_move(
            'in_invoice', self.partner_b, price=0.25,
            adjustment='supplier_buy')

        dashboard = self.env['petroleum.desk.dashboard']
        self.assertEqual(customer_debit.petro_margin_total, 100.0)
        self.assertEqual(
            dashboard._supplier_adjustment_margin(supplier_credit), 50.0)
        self.assertEqual(
            dashboard._supplier_adjustment_margin(supplier_debit), -25.0)

    def test_remaining_supplier_document_is_not_counted_twice(self):
        remaining_credit = self._create_move(
            'in_refund', self.partner_b, price=0.5,
            adjustment='supplier_buy', scope='remaining')
        adjustments = self.env[
            'petroleum.desk.dashboard'
        ]._get_supplier_margin_adjustments(self._filters())
        self.assertNotIn(remaining_credit, adjustments)

    def test_partial_sold_revision_splits_and_updates_allocation_cost(self):
        position = self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 100.0,
            'buy_price': 10.0,
        })
        self.env['petroleum.daily.position.allocation'].create({
            'position_line_id': position.id,
            'deal_id': self.deal.id,
            'deal_line_id': self.deal.line_ids.id,
            'quantity': 100.0,
            'buy_price': 10.0,
        })

        moves = position.action_create_sold_price_adjustments(
            new_buy_price=8.0, quantity=40.0, note='Partial reduction')
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves.invoice_line_ids.quantity, 40.0)
        self.assertEqual(moves.invoice_line_ids.price_unit, 2.0)
        self.assertEqual(
            sorted((a.quantity, a.buy_price) for a in position.allocation_ids),
            [(40.0, 8.0), (60.0, 10.0)],
        )

        position.action_create_sold_price_adjustments(
            new_buy_price=7.0, quantity=100.0, note='Second reduction')
        self.assertEqual(set(position.allocation_ids.mapped('buy_price')), {7.0})
