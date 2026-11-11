from odoo import api, models


class PetroleumDailyPositionLine(models.Model):
    _inherit = 'petroleum.daily.position.line'

    def _petro_register_contribution(self):
        self.ensure_one()
        if self.rolled_forward_on:
            return 0.0
        return self.qty_remaining

    def _petro_register_key(self):
        self.ensure_one()
        return (
            self.company_id.id,
            self.product_id.id,
            self.depot_id.id or 0,
            self._petro_register_contribution(),
        )

    def _petro_hint_key_change(self, old, new, origin):
        register = self.env['petroleum.stock.register']
        if old[:3] == new[:3]:
            company = self.env['res.company'].browse(new[0])
            product = self.env['product.product'].browse(new[1])
            depot = self.env['petroleum.depot'].browse(new[2]) if new[2] else self.env['petroleum.depot']
            register._hint_delta(company, product, depot, new[3] - old[3], origin, origin.date)
            return
        old_company = self.env['res.company'].browse(old[0])
        old_product = self.env['product.product'].browse(old[1])
        old_depot = self.env['petroleum.depot'].browse(old[2]) if old[2] else self.env['petroleum.depot']
        register._hint_delta(
            old_company, old_product, old_depot, -old[3], origin, origin.date)
        new_company = self.env['res.company'].browse(new[0])
        new_product = self.env['product.product'].browse(new[1])
        new_depot = self.env['petroleum.depot'].browse(new[2]) if new[2] else self.env['petroleum.depot']
        register._hint_delta(
            new_company, new_product, new_depot, new[3], origin, origin.date)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        register = self.env['petroleum.stock.register']
        for line in lines:
            register._hint_delta(
                line.company_id, line.product_id, line.depot_id,
                line._petro_register_contribution(), line, line.date,
            )
        return lines

    def write(self, vals):
        watched = {
            'qty_opening', 'qty_bought', 'depot_id', 'rolled_forward_on',
            'product_id', 'company_id',
        }
        before = {}
        if watched.intersection(vals):
            before = {line.id: line._petro_register_key() for line in self}
        res = super().write(vals)
        for line in self:
            old = before.get(line.id)
            if old:
                line._petro_hint_key_change(old, line._petro_register_key(), line)
        return res

    def unlink(self):
        register = self.env['petroleum.stock.register']
        for line in self:
            register._hint_delta(
                line.company_id, line.product_id, line.depot_id,
                -line._petro_register_contribution(), line, line.date,
            )
        return super().unlink()


class PetroleumDailyPositionAllocation(models.Model):
    _inherit = 'petroleum.daily.position.allocation'

    def _petro_register_effective(self):
        self.ensure_one()
        return self.quantity if self.state == 'active' else 0.0

    def _petro_hint_allocation(self, delta):
        lot = self.position_line_id
        if not lot:
            return
        self.env['petroleum.stock.register']._hint_delta(
            lot.company_id, lot.product_id, lot.depot_id, delta,
            self.deal_id or lot, self.deal_id.date or lot.date,
        )

    @api.model_create_multi
    def create(self, vals_list):
        allocations = super().create(vals_list)
        for allocation in allocations:
            allocation._petro_hint_allocation(-allocation._petro_register_effective())
        return allocations

    def write(self, vals):
        before = {}
        if 'quantity' in vals or 'state' in vals or 'position_line_id' in vals:
            before = {allocation.id: (
                allocation.position_line_id.id,
                allocation._petro_register_effective(),
            ) for allocation in self}
        res = super().write(vals)
        for allocation in self:
            old = before.get(allocation.id)
            if not old:
                continue
            old_lot = self.env['petroleum.daily.position.line'].browse(old[0])
            if old_lot and old_lot != allocation.position_line_id:
                self.env['petroleum.stock.register']._hint_delta(
                    old_lot.company_id, old_lot.product_id, old_lot.depot_id,
                    old[1], allocation.deal_id or old_lot,
                    allocation.deal_id.date or old_lot.date,
                )
                allocation._petro_hint_allocation(-allocation._petro_register_effective())
            else:
                allocation._petro_hint_allocation(
                    -(allocation._petro_register_effective() - old[1]))
        return res

    def unlink(self):
        for allocation in self:
            allocation._petro_hint_allocation(allocation._petro_register_effective())
        return super().unlink()
