from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestDashboardDealDateFilter(AccountTestInvoicingCommon):
    """The desk reports a deal in its own period, not the invoicing period.

    Deals are invoiced when the truck loads, which regularly happens in the
    month after the deal date, so filtering on the document date used to split
    one deal across two periods.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sales_team.group_sale_manager')
        cls.product_a.write({
            'fuel_ok': True,
            'default_code': 'PMS',
            'purchase_ok': True,
            'purchase_method': 'purchase',
        })
        cls.partner_a.customer_rank = 1
        cls.partner_b.supplier_rank = 1

        cls.today = fields.Date.today()
        first_of_month = cls.today.replace(day=1)
        cls.deal_date = (first_of_month - relativedelta(months=1)).replace(day=15)
        cls.deal_month = (
            cls.deal_date.replace(day=1), first_of_month - timedelta(days=1))
        cls.this_month = (first_of_month, cls.today)

        cls.deal = cls.env['petroleum.deal'].create({
            'partner_id': cls.partner_a.id,
            'date': cls.deal_date,
            'line_ids': [fields.Command.create({
                'product_id': cls.product_a.id,
                'quantity': 100.0,
                'sell_price': 10.0,
                'buy_price': 7.0,
                'supplier_id': cls.partner_b.id,
            })],
        })
        # Loaded and invoiced in the month after the deal.
        cls.invoice = cls._create_move(
            'out_invoice', cls.partner_a, price=10.0, buy=7.0, deal=cls.deal)
        cls.invoice.action_post()

    @classmethod
    def _create_move(cls, move_type, partner, price, buy=0.0, deal=None,
                     invoice_date=None, **vals):
        return cls.env['account.move'].create({
            'move_type': move_type,
            'partner_id': partner.id,
            'invoice_date': invoice_date or cls.today,
            'deal_id': deal.id if deal else False,
            'invoice_line_ids': [cls._prepare_invoice_line(
                product_id=cls.product_a,
                quantity=100.0,
                price_unit=price,
                petro_buy_price=buy,
                tax_ids=cls.env['account.tax'],
            )],
            **vals,
        })

    def _filters(self, window):
        return self.env['petroleum.desk.dashboard']._parse_filters({
            'date_from': window[0],
            'date_to': window[1],
        })

    def _dashboard_data(self, window):
        return self.env['petroleum.desk.dashboard'].get_dashboard_data({
            'date_from': window[0],
            'date_to': window[1],
        })

    def test_desk_date_follows_the_deal(self):
        self.assertEqual(self.invoice.invoice_date, self.today)
        self.assertEqual(self.invoice.petro_deal_date, self.deal_date)

    def test_desk_date_follows_a_moved_deal(self):
        new_date = self.deal_date - timedelta(days=3)
        self.deal.date = new_date
        self.assertEqual(self.invoice.petro_deal_date, new_date)

    def test_document_without_deal_keeps_its_own_date(self):
        loose = self._create_move('out_invoice', self.partner_a, price=10.0)
        self.assertEqual(loose.petro_deal_date, self.today)

    def test_credit_note_follows_the_corrected_deal(self):
        credit = self._create_move(
            'out_refund', self.partner_a, price=1.0,
            petro_original_move_id=self.invoice.id,
            petro_price_adjustment='customer_sell',
            petro_adjustment_scope='sold')
        self.assertFalse(credit.deal_id)
        self.assertEqual(credit.petro_deal_date, self.deal_date)

    def test_vendor_bill_and_invoice_share_the_period(self):
        bill = self._create_move(
            'in_invoice', self.partner_b, price=7.0, deal=self.deal)
        dashboard = self.env['petroleum.desk.dashboard']
        deal_month = self._filters(self.deal_month)
        self.assertTrue(dashboard._invoice_in_period(bill, deal_month))
        self.assertTrue(dashboard._invoice_in_period(self.invoice, deal_month))
        this_month = self._filters(self.this_month)
        self.assertFalse(dashboard._invoice_in_period(bill, this_month))

    def test_invoice_collected_in_the_deal_period_only(self):
        dashboard = self.env['petroleum.desk.dashboard']
        self.assertIn(
            self.invoice,
            dashboard._get_dashboard_invoices(self._filters(self.deal_month)))
        self.assertNotIn(
            self.invoice,
            dashboard._get_dashboard_invoices(self._filters(self.this_month)))

    def test_margin_trend_buckets_on_the_deal_date(self):
        dashboard = self.env['petroleum.desk.dashboard']
        flt = self._filters(self.deal_month)
        self.assertEqual(
            dashboard._margin_by_deal_date(self.invoice, flt, self.deal_date),
            300.0)
        self.assertEqual(
            dashboard._margin_by_deal_date(self.invoice, flt, self.today), 0.0)

    def test_kpis_report_the_deal_in_its_own_month(self):
        data = self._dashboard_data(self.deal_month)
        self.assertEqual(data['kpis']['deal_invoices_count'], 1)
        self.assertEqual(data['kpis']['litres_raw']['PMS'], 100.0)
        self.assertEqual(data['charts']['deals_pipeline']['total_count'], 1)

        data = self._dashboard_data(self.this_month)
        self.assertEqual(data['kpis']['deal_invoices_count'], 0)
        self.assertEqual(data['kpis']['litres_raw']['PMS'], 0.0)
        self.assertEqual(data['charts']['deals_pipeline']['total_count'], 0)
