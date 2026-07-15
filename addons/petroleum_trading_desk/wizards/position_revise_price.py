from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class PetroleumDailyPositionRevisePrice(models.TransientModel):
    _name = 'petroleum.daily.position.revise.price'
    _description = 'Revise Daily Position Buy Price'

    position_line_id = fields.Many2one(
        'petroleum.daily.position.line', string='Position Lot', required=True,
        ondelete='cascade')
    product_id = fields.Many2one(related='position_line_id.product_id')
    supplier_id = fields.Many2one(related='position_line_id.supplier_id')
    date = fields.Date(related='position_line_id.date')
    currency_id = fields.Many2one(related='position_line_id.currency_id')
    current_buy_price = fields.Float(
        related='position_line_id.buy_price', string='Current Buy Price')
    qty_remaining = fields.Float(
        related='position_line_id.qty_remaining', string='Remaining Litres')
    new_buy_price = fields.Float(
        string='New Buy Price', digits='Product Price', required=True)
    price_drop = fields.Float(
        string='Drop / Litre', compute='_compute_credit', digits='Product Price')
    credit_amount = fields.Monetary(
        string='Credit Amount', compute='_compute_credit',
        currency_field='currency_id')
    matching_lot_id = fields.Many2one(
        'petroleum.daily.position.line', string='Matching Lot',
        compute='_compute_matching_lot')
    merge_into_matching = fields.Boolean(
        string='Merge into matching lot', default=True,
        help='If another same-day lot already exists at the new buy price, '
             'move remaining litres onto that lot.')
    create_credit_note = fields.Boolean(
        string='Create supplier credit note', default=True,
        help='Draft a vendor credit note for remaining litres × price drop '
             '(when the new price is lower).')
    note = fields.Char(
        string='Reason / Note', required=True,
        default='Supplier price reduction on remaining stock')

    @api.depends('position_line_id', 'new_buy_price')
    def _compute_matching_lot(self):
        for wiz in self:
            if wiz.position_line_id and wiz.new_buy_price:
                wiz.matching_lot_id = wiz.position_line_id._find_merge_target(
                    wiz.new_buy_price)
            else:
                wiz.matching_lot_id = False

    @api.depends('current_buy_price', 'new_buy_price', 'qty_remaining', 'currency_id')
    def _compute_credit(self):
        for wiz in self:
            drop = wiz.current_buy_price - wiz.new_buy_price
            wiz.price_drop = drop if drop > 0 else 0.0
            wiz.credit_amount = (
                wiz.price_drop * wiz.qty_remaining if wiz.price_drop else 0.0)

    @api.onchange('matching_lot_id')
    def _onchange_matching_lot(self):
        if self.matching_lot_id:
            self.merge_into_matching = True

    @api.onchange('new_buy_price', 'current_buy_price')
    def _onchange_new_price(self):
        if self.new_buy_price and self.current_buy_price:
            precision = (
                self.currency_id.decimal_places if self.currency_id else 2)
            if float_compare(
                    self.current_buy_price, self.new_buy_price,
                    precision_digits=precision) > 0:
                self.create_credit_note = True

    def action_confirm(self):
        self.ensure_one()
        line = self.position_line_id
        if not line:
            raise UserError(_('Select a position lot to revise.'))
        result = line.action_revise_buy_price(
            new_buy_price=self.new_buy_price,
            note=self.note,
            merge_into_matching=self.merge_into_matching,
            create_credit_note=self.create_credit_note,
        )
        credit = result['credit_note']
        if credit:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Supplier Credit Note'),
                'res_model': 'account.move',
                'res_id': credit.id,
                'view_mode': 'form',
                'target': 'current',
            }
        surviving = result['surviving_line']
        if result['merged']:
            message = _(
                'Revised %(qty)s L from %(old)s to %(new)s and merged into the '
                'existing @%(new)s lot.',
                qty=result['transferred_qty'],
                old=result['old_price'],
                new=result['new_price'],
            )
        else:
            message = _(
                'Buy price revised from %(old)s to %(new)s on %(qty)s L remaining.',
                old=result['old_price'],
                new=result['new_price'],
                qty=result['transferred_qty'],
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Buy price revised'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'petroleum.daily.position.line',
                    'res_id': surviving.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'current',
                },
            },
        }
