from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PetroleumDeal(models.Model):
    _name = 'petroleum.deal'
    _description = 'Trading Deal (Loading)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(default=lambda self: _('New'), copy=False, readonly=True, index=True)
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True,
        domain="[('customer_rank', '>', 0)]")
    depot_id = fields.Many2one('petroleum.depot', string='Loading Depot')

    truck_id = fields.Many2one('truck.management', string='Truck')
    driver_id = fields.Many2one(
        'res.partner', string='Driver', domain="[('is_driver', '=', True)]")
    driver_id_no = fields.Char(string='Driver ID', related='driver_id.id_no', readonly=True)
    epra_no = fields.Char(string='EPRA No.')
    compartment_plan = fields.Char(string='Compartment Plan', help='e.g. 2:3:2:3')

    grade_display = fields.Char(
        string='Product(s)', compute='_compute_line_summary', store=True)
    supplier_display = fields.Char(
        string='Supplier(s)', compute='_compute_line_summary', store=True)

    line_ids = fields.One2many('petroleum.deal.line', 'deal_id', string='Products', copy=True)

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related='company_id.currency_id')

    total_qty = fields.Float(string='Total Litres', compute='_compute_amounts', store=True)
    amount_sell = fields.Monetary(string='Sell Total', compute='_compute_amounts', store=True)
    amount_buy = fields.Monetary(string='Buy Total', compute='_compute_amounts', store=True)
    margin_total = fields.Monetary(string='Margin', compute='_compute_amounts', store=True)
    amount_paid = fields.Monetary(string='Paid', compute='_compute_paid', store=True)
    balance = fields.Monetary(string='Balance', compute='_compute_paid', store=True)

    state = fields.Selection([
        ('draft', 'Quotation'),
        ('proforma', 'Proforma Sent'),
        ('confirmed', 'Confirmed'),
        ('loaded', 'Loaded'),
        ('done', 'Settled'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True, string='Status')

    sale_order_id = fields.Many2one('sale.order', readonly=True, copy=False)
    trip_id = fields.Many2one('trip.management', readonly=True, copy=False)
    purchase_order_ids = fields.Many2many(
        'purchase.order', string='Purchase Orders', copy=False)
    invoice_ids = fields.Many2many(
        'account.move', compute='_compute_links', string='Invoices')
    bill_ids = fields.Many2many(
        'account.move', compute='_compute_links', string='Vendor Bills')
    payment_ids = fields.Many2many('account.payment', string='Payments', copy=False)

    invoice_count = fields.Integer(compute='_compute_links')
    bill_count = fields.Integer(compute='_compute_links')
    po_count = fields.Integer(compute='_compute_links')
    payment_count = fields.Integer(compute='_compute_payment_count')

    notes = fields.Text()
    is_not_sold = fields.Boolean(
        string='Not Sold Yet', compute='_compute_is_not_sold', store=True)

    # ------------------------------------------------------------------
    @api.depends('partner_id', 'partner_id.name')
    def _compute_is_not_sold(self):
        for deal in self:
            name = (deal.partner_id.name or '').strip().upper()
            deal.is_not_sold = name in {'NOT SOLD', 'NOTSOLD', 'UNSOLD'}

    @staticmethod
    def _line_product_label(product):
        if not product:
            return ''
        code = (product.default_code or '').strip()
        if code:
            return code.upper()
        name = (product.display_name or '').upper()
        for grade in ('PMS', 'AGO', 'IK', 'DIESEL', 'PETROL'):
            if grade in name:
                return grade
        return product.display_name or ''

    @api.depends(
        'line_ids.product_id', 'line_ids.product_id.default_code',
        'line_ids.supplier_id', 'line_ids.supplier_id.name',
    )
    def _compute_line_summary(self):
        for deal in self:
            grades, suppliers = [], []
            seen_grades, seen_suppliers = set(), set()
            for line in deal.line_ids:
                label = deal._line_product_label(line.product_id)
                if label and label not in seen_grades:
                    seen_grades.add(label)
                    grades.append(label)
                name = (line.supplier_id.name or '').strip()
                if name and name not in seen_suppliers:
                    seen_suppliers.add(name)
                    suppliers.append(name)
            deal.grade_display = ', '.join(grades)
            deal.supplier_display = ', '.join(suppliers)

    @api.depends('line_ids.quantity', 'line_ids.price_subtotal',
                 'line_ids.cost_subtotal', 'line_ids.margin')
    def _compute_amounts(self):
        for deal in self:
            deal.total_qty = sum(deal.line_ids.mapped('quantity'))
            deal.amount_sell = sum(deal.line_ids.mapped('price_subtotal'))
            deal.amount_buy = sum(deal.line_ids.mapped('cost_subtotal'))
            deal.margin_total = sum(deal.line_ids.mapped('margin'))

    @api.depends('payment_ids.amount', 'payment_ids.state', 'amount_sell')
    def _compute_paid(self):
        for deal in self:
            paid = sum(deal.payment_ids.filtered(
                lambda p: p.state in ('paid', 'posted', 'in_process')).mapped('amount'))
            deal.amount_paid = paid
            deal.balance = deal.amount_sell - paid

    @api.depends('payment_ids')
    def _compute_payment_count(self):
        for deal in self:
            deal.payment_count = len(deal.payment_ids)

    @api.onchange('truck_id')
    def _onchange_truck_id(self):
        if self.truck_id:
            if self.truck_id.driver_id:
                self.driver_id = self.truck_id.driver_id
            if not self.compartment_plan and self.truck_id.loading_plan:
                self.compartment_plan = self.truck_id.loading_plan

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('petroleum.deal') or _('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def _prepare_products(self):
        """Fuel is traded back-to-back with no warehouse: don't create
        deliveries/receipts, and invoice/bill on the ordered quantity."""
        templates = self.line_ids.mapped('product_id').product_tmpl_id
        vals = {}
        if any(t.is_storable for t in templates):
            vals['is_storable'] = False
        if any(t.invoice_policy != 'order' for t in templates):
            vals['invoice_policy'] = 'order'
        if 'purchase_method' in templates._fields and any(
                t.purchase_method != 'purchase' for t in templates):
            vals['purchase_method'] = 'purchase'
        if vals:
            templates.write(vals)

    def _prepare_sale_order(self):
        self.ensure_one()
        lines = []
        for line in self.line_ids:
            lines.append((0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sell_price,
                'petro_supplier_id': line.supplier_id.id,
                'petro_buy_price': line.buy_price,
            }))
        return {
            'partner_id': self.partner_id.id,
            'depot_id': self.depot_id.id,
            'date_order': fields.Datetime.now(),
            'origin': self.name,
            'order_line': lines,
        }

    def action_send_proforma(self):
        self.ensure_one()
        self._check_lines()
        if self.state == 'draft':
            self.state = 'proforma'
        return self.env.ref('petroleum_trading_desk.action_report_deal_proforma').report_action(self)

    def action_confirm(self):
        for deal in self:
            deal._check_lines()
            if not deal.truck_id:
                raise UserError(_('Assign a truck before confirming the deal.'))
            if deal.sale_order_id:
                raise UserError(_('This deal already has a sale order.'))
            deal._prepare_products()
            so = self.env['sale.order'].create(deal._prepare_sale_order())
            so.action_confirm()
            pos = self.env['purchase.order'].search([('origin', '=', so.name)])
            for po in pos:
                if po.state in ('draft', 'sent'):
                    po.button_confirm()
            trip = self.env['trip.management'].create({
                'truck_id': deal.truck_id.id,
                'purchase_order_id': pos[:1].id,
                'date': deal.date,
                'depot_id': deal.depot_id.id,
                'epra_no': deal.epra_no,
                'compartment_plan': deal.compartment_plan,
            })
            self.env['trip.sale'].create({'trip_id': trip.id, 'sale_order_id': so.id})
            for po in pos:
                po.write({
                    'truck_id': deal.truck_id.id,
                    'trip_id': trip.id,
                    'depot_id': deal.depot_id.id,
                    'epra_no': deal.epra_no,
                    'compartment_plan': deal.compartment_plan,
                })
            deal.write({
                'sale_order_id': so.id,
                'trip_id': trip.id,
                'purchase_order_ids': [(6, 0, pos.ids)],
                'state': 'confirmed',
            })
        return True

    def action_load(self):
        for deal in self:
            if not deal.sale_order_id:
                raise UserError(_('Confirm the deal first.'))
            # customer invoice — skip until a real client is assigned
            if not deal.is_not_sold:
                invoices = deal.sale_order_id._create_invoices()
                invoices.action_post()
                invoices.write({'deal_id': deal.id})
                deal._reconcile_payments(invoices)
            # vendor bills
            for po in deal.purchase_order_ids:
                if po.invoice_status == 'to invoice':
                    po.action_create_invoice()
            bills = deal.purchase_order_ids.invoice_ids.filtered(
                lambda m: m.move_type == 'in_invoice' and m.state == 'draft')
            if bills:
                bills.write({'invoice_date': deal.date, 'deal_id': deal.id})
                bills.action_post()
            if deal.trip_id:
                deal.trip_id.action_start()
            deal.state = 'loaded'
        return True

    def _reconcile_payments(self, invoices):
        """Match the deal's customer payments against the freshly posted
        invoice so the invoice shows Paid/Partially Paid automatically."""
        self.ensure_one()
        if not self.payment_ids or not invoices:
            return
        candidate = (invoices.line_ids | self.payment_ids.move_id.line_ids).filtered(
            lambda l: l.account_id.account_type == 'asset_receivable'
            and not l.reconciled)
        by_account = {}
        for line in candidate:
            by_account.setdefault(line.account_id, self.env['account.move.line'])
            by_account[line.account_id] |= line
        for lines in by_account.values():
            if len(lines) > 1:
                try:
                    lines.reconcile()
                except Exception:  # noqa: BLE001 - reconciliation is best-effort
                    pass

    def action_register_payment(self):
        return self._action_open_bulk_payment('customer')

    def action_pay_supplier_bills(self):
        return self._action_open_bulk_payment('supplier')

    def _action_open_bulk_payment(self, payment_side):
        self.ensure_one()
        title = _('Register Payment') if payment_side == 'customer' else _('Pay Supplier Bills')
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'petroleum.desk.bulk.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_side': payment_side,
                'default_deal_ids': [(6, 0, self.ids)],
                'default_company_id': self.company_id.id,
            },
        }

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Bulk list actions (Actions menu on multi-select)
    # ------------------------------------------------------------------
    def _bulk_notify(self, title, done, skipped, errors):
        if errors:
            detail = '\n'.join(errors[:15])
            if len(errors) > 15:
                detail += _('\n… and %d more.') % (len(errors) - 15)
            message = _('Done: %d · Skipped: %d · Failed: %d\n%s') % (
                done, skipped, len(errors), detail)
            ntype = 'warning' if done else 'danger'
            sticky = True
        else:
            message = _('Done: %d · Skipped: %d') % (done, skipped)
            ntype = 'success'
            sticky = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': ntype,
                'sticky': sticky,
            },
        }

    def action_bulk_confirm(self):
        ctx = dict(self.env.context, mail_create_nosubscribe=True, tracking_disable=True)
        done = skipped = 0
        errors = []
        for deal in self.with_context(**ctx):
            if deal.state not in ('draft', 'proforma'):
                skipped += 1
                continue
            try:
                deal.action_confirm()
                done += 1
            except UserError as exc:
                errors.append('%s — %s' % (deal.display_name, exc.args[0]))
            except Exception as exc:  # noqa: BLE001
                errors.append('%s — %s' % (deal.display_name, exc))
        return self._bulk_notify(_('Confirm deals'), done, skipped, errors)

    def action_bulk_load(self):
        ctx = dict(self.env.context, mail_create_nosubscribe=True, tracking_disable=True)
        done = skipped = 0
        errors = []
        for deal in self.with_context(**ctx):
            if deal.state != 'confirmed':
                skipped += 1
                continue
            try:
                deal.action_load()
                done += 1
            except UserError as exc:
                errors.append('%s — %s' % (deal.display_name, exc.args[0]))
            except Exception as exc:  # noqa: BLE001
                errors.append('%s — %s' % (deal.display_name, exc))
        return self._bulk_notify(_('Load & invoice'), done, skipped, errors)

    def action_bulk_done(self):
        eligible = self.filtered(lambda d: d.state == 'loaded')
        skipped = len(self) - len(eligible)
        errors = []
        done = 0
        for deal in eligible:
            try:
                deal.action_done()
                done += 1
            except UserError as exc:
                errors.append('%s — %s' % (deal.display_name, exc.args[0]))
            except Exception as exc:  # noqa: BLE001
                errors.append('%s — %s' % (deal.display_name, exc))
        return self._bulk_notify(_('Mark settled'), done, skipped, errors)

    def _check_lines(self):
        for deal in self:
            if not deal.line_ids:
                raise UserError(_('Add at least one product line.'))
            for line in deal.line_ids:
                if not line.supplier_id:
                    raise UserError(_('Choose a supplier for %s.') % line.product_id.display_name)

    @api.model
    def backfill_move_deal_links(self):
        """Link legacy sale/purchase invoices to their deal (idempotent)."""
        for deal in self.search([('sale_order_id', '!=', False)]):
            moves = deal.sale_order_id.invoice_ids
            if deal.purchase_order_ids:
                moves |= deal.purchase_order_ids.invoice_ids
            to_link = moves.filtered(lambda m: not m.deal_id)
            if to_link:
                to_link.write({'deal_id': deal.id})

    # ------------------------------------------------------------------
    # Smart-button actions
    # ------------------------------------------------------------------
    def action_view_invoices(self):
        self.ensure_one()
        return self._action_open_moves(self.invoice_ids, _('Invoices'))

    def action_view_bills(self):
        self.ensure_one()
        return self._action_open_moves(self.bill_ids, _('Vendor Bills'))

    def _action_open_moves(self, moves, title):
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'account.move',
            'domain': [('id', 'in', moves.ids)],
            'view_mode': 'list,form',
        }

    def action_view_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payments'),
            'res_model': 'account.payment',
            'domain': [('id', 'in', self.payment_ids.ids)],
            'view_mode': 'list,form',
        }


class PetroleumDealLine(models.Model):
    _name = 'petroleum.deal.line'
    _description = 'Trading Deal Line'

    deal_id = fields.Many2one('petroleum.deal', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('fuel_ok', '=', True)]")
    quantity = fields.Float(string='Litres', default=0.0, required=True)
    sell_price = fields.Float(string='Sell Price', digits='Product Price')
    buy_price = fields.Float(string='Buy Price', digits='Product Price')
    supplier_id = fields.Many2one(
        'res.partner', string='Supplier', domain="[('supplier_rank', '>', 0)]")
    currency_id = fields.Many2one(related='deal_id.currency_id')
    price_subtotal = fields.Monetary(compute='_compute_subtotals', store=True, string='Sell Subtotal')
    cost_subtotal = fields.Monetary(compute='_compute_subtotals', store=True, string='Buy Subtotal')
    margin = fields.Monetary(compute='_compute_subtotals', store=True, string='Margin')

    @api.depends('quantity', 'sell_price', 'buy_price')
    def _compute_subtotals(self):
        for line in self:
            line.price_subtotal = line.quantity * line.sell_price
            line.cost_subtotal = line.quantity * line.buy_price
            line.margin = line.quantity * (line.sell_price - line.buy_price)

    @api.onchange('product_id', 'supplier_id')
    def _onchange_product_prices(self):
        for line in self:
            if not line.product_id:
                continue
            dp = self.env['petroleum.daily.price'].get_latest(
                line.product_id.id, line.supplier_id.id if line.supplier_id else False)
            if not dp and line.supplier_id:
                dp = self.env['petroleum.daily.price'].get_latest(line.product_id.id)
            if dp:
                if not line.sell_price:
                    line.sell_price = dp.sell_price
                if not line.buy_price:
                    line.buy_price = dp.buy_price
                if not line.supplier_id and dp.supplier_id:
                    line.supplier_id = dp.supplier_id

    def _sync_daily_price(self):
        DailyPrice = self.env['petroleum.daily.price']
        for line in self:
            if line.buy_price:
                DailyPrice.upsert_from_deal_line(line)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._sync_daily_price()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('buy_price', 'sell_price', 'product_id', 'supplier_id')):
            self._sync_daily_price()
        return res
