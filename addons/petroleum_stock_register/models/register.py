import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import config
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

LOCK_BASE = 820_000


class PetroleumStockRegister(models.AbstractModel):
    _name = 'petroleum.stock.register'
    _description = 'Petroleum Stock Register'

    @api.model
    def _schedule(self, company):
        """Apply after the desk transaction commits. Tests call apply() themselves."""
        if not company or company.petro_stock_register_mode != 'live':
            return
        if config['test_enable'] or self.env.context.get('petro_register_no_schedule'):
            return
        pending = getattr(self.env.cr, '_petro_register_companies', None)
        if pending is None:
            pending = set()
            self.env.cr._petro_register_companies = pending
            registry = self.env.registry
            uid = self.env.uid

            def _run(company_ids=pending):
                with registry.cursor() as cr:
                    env = api.Environment(cr, uid, {'petro_register_move': True})
                    for company_id in list(company_ids):
                        try:
                            env['petroleum.stock.register']._apply_company(company_id)
                            cr.commit()
                        except Exception:
                            _logger.exception(
                                'Petroleum stock register failed for company %s.',
                                company_id,
                            )
                            cr.rollback()

            self.env.cr.postcommit.add(_run)
        pending.add(company.id)

    @api.model
    def _hint_delta(self, company, product, depot, delta, origin, business_date):
        if not company or company.petro_stock_register_mode != 'live' or not product:
            return self.env['petroleum.stock.register.hint']
        rounding = product.uom_id.rounding or 0.01
        if float_is_zero(delta, precision_rounding=rounding):
            return self.env['petroleum.stock.register.hint']
        hint = self.env['petroleum.stock.register.hint'].sudo().create({
            'company_id': company.id,
            'product_id': product.id,
            'depot_id': depot.id if depot else False,
            'expected_delta': delta,
            'business_date': business_date or fields.Date.context_today(self),
            'origin_model': origin._name,
            'origin_res_id': origin.id,
            'origin': origin.display_name,
        })
        self._schedule(company)
        return hint

    @api.model
    def _apply_company(self, company_id, opening=False, repair=False):
        company = self.env['res.company'].browse(company_id).exists()
        if not company:
            return
        if company.petro_stock_register_mode != 'live' and not opening:
            return
        self.env.cr.execute(
            'SELECT pg_advisory_xact_lock(%s)',
            [LOCK_BASE + company.id],
        )
        company._petro_ensure_register_warehouse()
        hints = self.env['petroleum.stock.register.hint'].search([
            ('company_id', '=', company.id),
            ('state', '=', 'pending'),
        ])
        keys = {(hint.product_id.id, hint.depot_id.id or 0) for hint in hints}
        if opening or repair:
            lines = self.env['petroleum.daily.position.line'].search([
                ('company_id', '=', company.id),
                ('rolled_forward_on', '=', False),
            ])
            keys.update(
                (line.product_id.id, line.depot_id.id or 0) for line in lines
            )
            quants = self.env['stock.quant'].sudo().search([
                ('company_id', '=', company.id),
                ('location_id.petro_register', '=', True),
                ('location_id.usage', '=', 'internal'),
            ])
            for quant in quants:
                depot_id = quant.location_id.petro_depot_id.id or 0
                if quant.location_id.petro_no_depot or quant.location_id.petro_depot_id:
                    keys.add((quant.product_id.id, depot_id))
        for product_id, depot_key in keys:
            product = self.env['product.product'].browse(product_id)
            depot = self.env['petroleum.depot'].browse(depot_key) if depot_key else self.env['petroleum.depot']
            key_hints = hints.filtered(
                lambda hint, product_id=product_id, depot_key=depot_key:
                hint.product_id.id == product_id and (hint.depot_id.id or 0) == depot_key
            )
            self._apply_key(company, product, depot, key_hints, opening=opening)

    @api.model
    def _target_qty(self, company, product, depot):
        lines = self.env['petroleum.daily.position.line'].search([
            ('company_id', '=', company.id),
            ('product_id', '=', product.id),
            ('rolled_forward_on', '=', False),
            ('depot_id', '=', depot.id if depot else False),
        ])
        return sum(lines.mapped('qty_remaining'))

    @api.model
    def _on_hand_qty(self, product, location):
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ])
        return sum(quants.mapped('quantity'))

    @api.model
    def _apply_key(self, company, product, depot, hints, opening=False):
        location = company._petro_register_location(depot)
        if not location:
            return
        rounding = product.uom_id.rounding or 0.01
        target = self._target_qty(company, product, depot)
        on_hand = self._on_hand_qty(product, location)
        gap = target - on_hand
        if opening:
            self._post_gap(
                company, product, location, gap,
                _('Opening balance'), fields.Date.context_today(self),
            )
            if hints:
                hints.write({'state': 'applied'})
            return
        hint_sum = sum(hints.mapped('expected_delta'))
        gap_matches = float_compare(gap, hint_sum, precision_rounding=rounding) == 0
        if float_is_zero(gap, precision_rounding=rounding) and gap_matches:
            if hints:
                hints.write({'state': 'applied'})
            return
        if hints and gap_matches:
            for hint in hints:
                move = self._post_gap(
                    company, product, location, hint.expected_delta,
                    hint.origin or hint.display_name, hint.business_date,
                )
                hint.write({
                    'state': 'applied',
                    'stock_move_id': move.id if move else False,
                })
            return
        move = self._post_gap(
            company, product, location, gap,
            _('Alignment'), fields.Date.context_today(self),
        )
        if not float_is_zero(gap, precision_rounding=rounding) or hints:
            self.env['petroleum.stock.register.variance'].sudo().create({
                'company_id': company.id,
                'product_id': product.id,
                'depot_id': depot.id if depot else False,
                'target_qty': target,
                'on_hand_qty': on_hand,
                'gap': gap,
                'stock_move_id': move.id if move else False,
                'note': _(
                    'On-hand was brought in line with Daily Position. '
                    'The labelled litre changes did not add up to that gap.'
                ),
            })
        if hints:
            hints.write({'state': 'variance'})

    @api.model
    def _post_gap(self, company, product, location, quantity, origin, business_date):
        rounding = product.uom_id.rounding or 0.01
        if float_is_zero(quantity, precision_rounding=rounding):
            return self.env['stock.move']
        supplier = company.partner_id.property_stock_supplier
        customer = company.partner_id.property_stock_customer
        if float_compare(quantity, 0.0, precision_rounding=rounding) > 0:
            source, destination = supplier, location
            amount = quantity
        else:
            source, destination = location, customer
            amount = -quantity
        if not source or not destination:
            _logger.error(
                'Petroleum stock register has no partner location for %s.',
                company.display_name,
            )
            return self.env['stock.move']
        return self.env['stock.move']._petro_post_register_move(
            product, source, destination, amount, company, origin, business_date,
        )


class PetroleumStockRegisterHint(models.Model):
    _name = 'petroleum.stock.register.hint'
    _description = 'Petroleum Stock Register Hint'
    _order = 'id'

    company_id = fields.Many2one('res.company', required=True, index=True)
    product_id = fields.Many2one('product.product', required=True, index=True)
    depot_id = fields.Many2one('petroleum.depot', index=True)
    expected_delta = fields.Float(digits='Product Unit of Measure', required=True)
    business_date = fields.Date(required=True)
    origin_model = fields.Char()
    origin_res_id = fields.Integer()
    origin = fields.Char()
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('applied', 'Applied'),
            ('variance', 'Variance'),
        ],
        default='pending', required=True, index=True,
    )
    stock_move_id = fields.Many2one('stock.move', copy=False)
    note = fields.Char()

    @api.model
    def _cron_repair(self):
        companies = self.env['res.company'].search([
            ('petro_stock_register_mode', '=', 'live'),
        ])
        register = self.env['petroleum.stock.register']
        for company in companies:
            register._apply_company(company.id, repair=True)


class PetroleumStockRegisterVariance(models.Model):
    _name = 'petroleum.stock.register.variance'
    _description = 'Petroleum Stock Register Variance'
    _order = 'id desc'

    company_id = fields.Many2one('res.company', required=True, index=True)
    product_id = fields.Many2one('product.product', required=True)
    depot_id = fields.Many2one('petroleum.depot')
    target_qty = fields.Float(digits='Product Unit of Measure')
    on_hand_qty = fields.Float(string='On Hand Before', digits='Product Unit of Measure')
    gap = fields.Float(digits='Product Unit of Measure')
    stock_move_id = fields.Many2one('stock.move')
    note = fields.Char()
