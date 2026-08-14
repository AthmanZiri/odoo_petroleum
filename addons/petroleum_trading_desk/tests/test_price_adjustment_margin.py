from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPriceAdjustmentMargin(AccountTestInvoicingCommon):

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

    def test_same_price_create_merges_into_rolled_opening_lot(self):
        Position = self.env['petroleum.daily.position.line']
        today = fields.Date.today()
        opening = Position.create({
            'date': today,
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_opening': 47000.0,
            'qty_bought': 0.0,
            'buy_price': 194.0,
        })
        merged = Position.create({
            'date': today,
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 76000.0,
            'buy_price': 194.0,
        })
        self.assertEqual(merged, opening)
        self.assertEqual(opening.qty_opening, 47000.0)
        self.assertEqual(opening.qty_bought, 76000.0)
        self.assertEqual(opening.qty_total, 123000.0)
        self.assertEqual(Position.search_count([
            ('date', '=', today),
            ('product_id', '=', self.product_a.id),
            ('supplier_id', '=', self.partner_b.id),
        ]), 1)

    def test_orphan_customer_sell_credit_is_on_dashboard(self):
        credit = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.partner_a.id,
            'invoice_date': fields.Date.today(),
            'petro_price_adjustment': 'customer_sell',
            'petro_adjustment_scope': 'sold',
            'invoice_line_ids': [self._prepare_invoice_line(
                product_id=self.product_a,
                quantity=10000.0,
                price_unit=0.5,
                tax_ids=self.env['account.tax'],
            )],
        })
        credit.action_post()
        self.assertEqual(credit.petro_margin_total, -5000.0)

        dashboard = self.env['petroleum.desk.dashboard']
        invoices = dashboard._get_dashboard_invoices(self._filters())
        self.assertIn(credit, invoices)
        self.assertEqual(
            dashboard._invoice_margin(credit, self._filters()), -5000.0)

    def test_shared_po_supplier_adjustment_counts_only_on_linked_deal(self):
        other_deal = self.env['petroleum.deal'].create({
            'partner_id': self.partner_a.id,
            'line_ids': [fields.Command.create({
                'product_id': self.product_a.id,
                'quantity': 50.0,
                'sell_price': 12.0,
                'buy_price': 7.0,
                'supplier_id': self.partner_b.id,
            })],
        })
        supplier_credit = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': self.partner_b.id,
            'invoice_date': fields.Date.today(),
            'deal_id': self.deal.id,
            'petro_price_adjustment': 'supplier_buy',
            'petro_adjustment_scope': 'sold',
            'invoice_line_ids': [self._prepare_invoice_line(
                product_id=self.product_a,
                quantity=90.0,
                price_unit=1.0,
                tax_ids=self.env['account.tax'],
            )],
        })
        supplier_credit.action_post()
        # Simulate a bulk PO shared by both deals that also lists this CN.
        po = self.env['purchase.order'].create({
            'partner_id': self.partner_b.id,
            'order_line': [fields.Command.create({
                'product_id': self.product_a.id,
                'product_qty': 100.0,
                'price_unit': 7.0,
            })],
        })
        self.deal.purchase_order_ids = [(4, po.id)]
        other_deal.purchase_order_ids = [(4, po.id)]
        po.invoice_ids = [(4, supplier_credit.id)]

        self.deal._compute_amounts()
        other_deal._compute_amounts()
        self.assertEqual(self.deal.adjustment_margin_total, 90.0)
        self.assertEqual(other_deal.adjustment_margin_total, 0.0)

    def _posted_po_with_bill(self, qty=100.0, price=10.0):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner_b.id,
            'order_line': [fields.Command.create({
                'product_id': self.product_a.id,
                'product_qty': qty,
                'price_unit': price,
            })],
        })
        po.write({'state': 'purchase'})
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_b.id,
            'invoice_date': fields.Date.today(),
            'invoice_origin': po.name,
            'invoice_line_ids': [self._prepare_invoice_line(
                product_id=self.product_a,
                quantity=qty,
                price_unit=price,
                tax_ids=self.env['account.tax'],
            )],
        })
        bill.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
        ).purchase_line_id = po.order_line[:1]
        bill.action_post()
        po.order_line._compute_qty_invoiced()
        po._compute_invoice()
        return po, bill

    def test_supplier_price_credit_does_not_reverse_qty_invoiced(self):
        po, bill = self._posted_po_with_bill()
        self.assertEqual(po.order_line.qty_invoiced, 100.0)

        credit = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': self.partner_b.id,
            'invoice_date': fields.Date.today(),
            'invoice_origin': po.name,
            'petro_price_adjustment': 'supplier_buy',
            'petro_adjustment_scope': 'sold',
            'petro_old_price': 10.0,
            'petro_new_price': 9.0,
            'invoice_line_ids': [self._prepare_invoice_line(
                product_id=self.product_a,
                quantity=90.0,
                price_unit=1.0,
                tax_ids=self.env['account.tax'],
            )],
        })
        credit.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
        ).purchase_line_id = po.order_line[:1]
        credit.action_post()
        po.order_line._compute_qty_invoiced()
        po._compute_invoice()

        self.assertEqual(po.order_line.qty_invoiced, 100.0)
        self.assertEqual(po.order_line.qty_to_invoice, 0.0)
        self.assertIn(credit, po.invoice_ids)
        self.assertIn(bill, po.invoice_ids)

    def test_sold_price_adjustment_sets_purchase_line_without_qty_change(self):
        po, _bill = self._posted_po_with_bill()
        position = self.env['petroleum.daily.position.line'].create({
            'date': fields.Date.today(),
            'product_id': self.product_a.id,
            'supplier_id': self.partner_b.id,
            'qty_bought': 100.0,
            'buy_price': 10.0,
            'purchase_order_id': po.id,
            'purchase_order_line_id': po.order_line.id,
        })
        self.env['petroleum.daily.position.allocation'].create({
            'position_line_id': position.id,
            'deal_id': self.deal.id,
            'deal_line_id': self.deal.line_ids.id,
            'quantity': 100.0,
            'buy_price': 10.0,
        })

        moves = position.action_create_sold_price_adjustments(
            new_buy_price=8.0, quantity=40.0, note='Sold reduction')
        moves.action_post()
        po.order_line._compute_qty_invoiced()
        po._compute_invoice()

        self.assertEqual(moves.petro_price_adjustment, 'supplier_buy')
        self.assertEqual(
            moves.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product'
            ).purchase_line_id, po.order_line)
        self.assertEqual(po.order_line.qty_invoiced, 100.0)
        self.assertIn(moves, po.invoice_ids)

    def test_orphan_extra_bill_line_relink_clears_qty_to_invoice(self):
        po, bill = self._posted_po_with_bill(qty=100.0, price=10.0)
        bill.button_draft()
        product_line = bill.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product')[:1]
        product_line.quantity = 90.0
        extra = bill.invoice_line_ids.create({
            'move_id': bill.id,
            'display_type': 'product',
            'name': 'remaining at new price',
            'quantity': 10.0,
            'price_unit': 12.0,
            'tax_ids': [fields.Command.set([])],
        })
        bill.action_post()
        po.order_line._compute_qty_invoiced()
        self.assertEqual(po.order_line.qty_invoiced, 90.0)
        self.assertEqual(po.order_line.qty_to_invoice, 10.0)

        linked = self.env['purchase.order']._petro_relink_orphan_vendor_bill_lines()
        po.order_line._compute_qty_invoiced()
        self.assertEqual(linked, 1)
        self.assertEqual(extra.purchase_line_id, po.order_line)
        self.assertEqual(po.order_line.qty_invoiced, 100.0)
        self.assertEqual(po.order_line.qty_to_invoice, 0.0)

    def test_untagged_price_refund_is_tagged_and_ignored_for_qty(self):
        po, _bill = self._posted_po_with_bill()
        credit = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': self.partner_b.id,
            'invoice_date': fields.Date.today(),
            'invoice_origin': po.name,
            'invoice_line_ids': [self._prepare_invoice_line(
                product_id=self.product_a,
                quantity=100.0,
                price_unit=0.5,
                tax_ids=self.env['account.tax'],
            )],
        })
        credit.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product'
        ).purchase_line_id = po.order_line[:1]
        credit.action_post()
        po.order_line._compute_qty_invoiced()
        self.assertEqual(po.order_line.qty_invoiced, 0.0)

        tagged = self.env['purchase.order']._petro_tag_price_only_refunds()
        po.order_line._compute_qty_invoiced()
        self.assertEqual(tagged, 1)
        self.assertEqual(credit.petro_price_adjustment, 'supplier_buy')
        self.assertEqual(po.order_line.qty_invoiced, 100.0)
