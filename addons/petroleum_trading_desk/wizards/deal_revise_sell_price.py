from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class PetroleumDealReviseSellPrice(models.TransientModel):
    _name = 'petroleum.deal.revise.sell.price'
    _description = 'Revise Customer Sell Price'

    deal_id = fields.Many2one(
        'petroleum.deal', required=True, ondelete='cascade')
    deal_line_id = fields.Many2one(
        'petroleum.deal.line', string='Deal Line', required=True,
        domain="[('deal_id', '=', deal_id)]")
    original_invoice_id = fields.Many2one(
        'account.move', string='Original Invoice', required=True,
        domain="[('deal_id', '=', deal_id), ('move_type', '=', 'out_invoice'), "
               "('state', '=', 'posted')]")
    product_id = fields.Many2one(related='deal_line_id.product_id')
    partner_id = fields.Many2one(related='deal_id.partner_id')
    currency_id = fields.Many2one(related='deal_id.currency_id')
    current_sell_price = fields.Float(
        string='Current Effective Sell Price', digits='Product Price',
        readonly=True)
    new_sell_price = fields.Float(
        string='New Sell Price', digits='Product Price', required=True)
    quantity = fields.Float(
        string='Affected Litres', required=True,
        digits='Product Unit of Measure')
    adjustment_per_litre = fields.Float(
        string='Adjustment / Litre', compute='_compute_adjustment',
        digits='Product Price')
    adjustment_amount = fields.Monetary(
        string='Adjustment Amount', compute='_compute_adjustment',
        currency_field='currency_id')
    note = fields.Char(
        string='Reason / Note', required=True,
        default='Customer price adjustment')

    @api.depends(
        'current_sell_price', 'new_sell_price', 'quantity', 'currency_id')
    def _compute_adjustment(self):
        for wizard in self:
            wizard.adjustment_per_litre = (
                wizard.new_sell_price - wizard.current_sell_price)
            wizard.adjustment_amount = abs(
                wizard.adjustment_per_litre * wizard.quantity)

    @api.onchange('deal_line_id')
    def _onchange_deal_line_id(self):
        if not self.deal_line_id:
            return
        adjustments = self.env['account.move'].search([
            ('deal_id', '=', self.deal_id.id),
            ('petro_price_adjustment', '=', 'customer_sell'),
            ('state', '=', 'posted'),
        ], order='invoice_date desc, id desc')
        latest = adjustments.filtered(
            lambda move: self.deal_line_id.product_id
            in move.invoice_line_ids.product_id)[:1]
        current_price = (
            latest.petro_new_price if latest else self.deal_line_id.sell_price)
        self.current_sell_price = current_price
        self.new_sell_price = current_price
        self.quantity = self.deal_line_id.quantity
        invoices = self.deal_id.invoice_ids.filtered(
            lambda move: move.move_type == 'out_invoice'
            and move.state == 'posted'
            and self.deal_line_id.product_id in move.invoice_line_ids.product_id)
        self.original_invoice_id = invoices[:1]

    def action_confirm(self):
        self.ensure_one()
        if self.quantity <= 0:
            raise UserError(_('Affected litres must be greater than zero.'))
        if self.quantity > self.deal_line_id.quantity:
            raise UserError(_(
                'Affected litres cannot exceed the deal line quantity (%s L).',
                self.deal_line_id.quantity,
            ))
        invoiced_quantity = sum(
            self.original_invoice_id.invoice_line_ids.filtered(
                lambda line: line.product_id == self.product_id
                and line.display_type not in (
                    'line_section', 'line_subsection', 'line_note')
            ).mapped('quantity'))
        if self.quantity > invoiced_quantity:
            raise UserError(_(
                'Affected litres cannot exceed the quantity on %(invoice)s '
                '(%(qty)s L).',
                invoice=self.original_invoice_id.display_name,
                qty=invoiced_quantity,
            ))
        precision = self.currency_id.decimal_places or 2
        comparison = float_compare(
            self.new_sell_price, self.current_sell_price,
            precision_digits=precision)
        if comparison == 0:
            raise UserError(_('New sell price is the same as the current price.'))

        original_line = self.original_invoice_id.invoice_line_ids.filtered(
            lambda line: line.product_id == self.product_id
            and line.display_type not in (
                'line_section', 'line_subsection', 'line_note'))[:1]
        taxes = original_line.tax_ids
        delta = abs(self.new_sell_price - self.current_sell_price)
        move_type = 'out_invoice' if comparison > 0 else 'out_refund'
        direction = _('increase') if comparison > 0 else _('reduction')
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner_id.id,
            'company_id': self.deal_id.company_id.id,
            'invoice_date': fields.Date.context_today(self),
            'deal_id': self.deal_id.id,
            'petro_price_adjustment': 'customer_sell',
            'petro_original_move_id': self.original_invoice_id.id,
            'petro_adjustment_scope': 'sold',
            'petro_old_price': self.current_sell_price,
            'petro_new_price': self.new_sell_price,
            'petro_adjustment_quantity': self.quantity,
            'invoice_origin': self.original_invoice_id.name,
            'ref': _('Customer price %(direction)s — %(deal)s',
                     direction=direction, deal=self.deal_id.name),
            'invoice_line_ids': [fields.Command.create({
                'product_id': self.product_id.id,
                'name': _(
                    'Customer price %(direction)s on %(product)s: '
                    '%(old)s → %(new)s (%(qty)s L). %(note)s',
                    direction=direction,
                    product=self.product_id.display_name,
                    old=self.current_sell_price,
                    new=self.new_sell_price,
                    qty=self.quantity,
                    note=self.note,
                ),
                'quantity': self.quantity,
                'price_unit': delta,
                'tax_ids': [fields.Command.set(taxes.ids)],
                'product_uom_id': self.product_id.uom_id.id,
            })],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Customer Debit Note') if comparison > 0 else _(
                'Customer Credit Note'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
