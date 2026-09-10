from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PetroleumDepot(models.Model):
    _name = 'petroleum.depot'
    _description = 'Depot / Loading Point'
    _order = 'name'

    name = fields.Char(string='Depot / Loading Point', required=True)
    code = fields.Char(string='Code')
    town = fields.Char(string='Town / Location')
    partner_id = fields.Many2one(
        'res.partner', string='Operator',
        help='Company that operates the depot/terminal (e.g. KPC, an OMC).')
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    _DEPOT_FK_TABLES = (
        'petroleum_deal',
        'petroleum_daily_position_line',
        'petroleum_daily_price',
        'sale_order',
        'purchase_order',
        'trip_management',
    )

    def init(self):
        super().init()
        self._merge_duplicate_names()

    @api.model
    def _merge_duplicate_names(self):
        """Keep one depot per name and retarget every foreign key at it.

        Traders can quick-create a second 'KPRL' from a deal. Confirm then
        looks for Daily Position lots on the new id and reports no stock,
        even though the lots sit on the original KPRL record.
        """
        cr = self.env.cr
        cr.execute("SELECT to_regclass('petroleum_depot')")
        if not cr.fetchone()[0]:
            return
        cr.execute("""
            SELECT array_agg(id ORDER BY id)
              FROM petroleum_depot
             GROUP BY lower(trim(name))
            HAVING count(*) > 1
        """)
        groups = [row[0] for row in cr.fetchall()]
        if not groups:
            return
        existing_tables = set()
        cr.execute("""
            SELECT table_name
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND column_name = 'depot_id'
               AND table_name = ANY(%s)
        """, [list(self._DEPOT_FK_TABLES)])
        existing_tables.update(row[0] for row in cr.fetchall())
        dupe_ids = []
        for ids in groups:
            keeper, dupes = ids[0], list(ids[1:])
            dupe_ids.extend(dupes)
            for table in self._DEPOT_FK_TABLES:
                if table not in existing_tables:
                    continue
                cr.execute(
                    f'UPDATE {table} SET depot_id = %s WHERE depot_id = ANY(%s)',
                    [keeper, dupes],
                )
        if dupe_ids:
            self.browse(dupe_ids).unlink()

    @api.model_create_multi
    def create(self, vals_list):
        """Reuse an existing depot when the trader types the same name again."""
        records = self.browse()
        new_vals = []
        for vals in vals_list:
            name = (vals.get('name') or '').strip()
            if name and not self.env.context.get('skip_depot_name_reuse'):
                vals = dict(vals, name=name)
                existing = self.with_context(active_test=False).search(
                    [('name', '=ilike', name)], limit=1)
                if existing:
                    updates = {
                        key: value for key, value in vals.items()
                        if key != 'name' and value and not existing[key]
                    }
                    if not existing.active:
                        updates['active'] = True
                    if updates:
                        existing.write(updates)
                    records |= existing
                    continue
            new_vals.append(vals)
        if new_vals:
            records |= super().create(new_vals)
        return records

    @api.constrains('name')
    def _check_unique_name(self):
        if self.env.context.get('skip_depot_name_reuse'):
            return
        for depot in self:
            name = (depot.name or '').strip()
            if not name:
                continue
            twin = self.with_context(active_test=False).search([
                ('id', '!=', depot.id),
                ('name', '=ilike', name),
            ], limit=1)
            if twin:
                raise ValidationError(_(
                    'A depot named "%(name)s" already exists. '
                    'Use the existing record instead of creating another.',
                    name=name,
                ))
