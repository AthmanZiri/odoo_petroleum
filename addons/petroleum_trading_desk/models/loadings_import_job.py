import json
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

IMPORT_CTX = {
    'mail_create_nosubscribe': True,
    'mail_notrack': True,
    'tracking_disable': True,
    'petro_bulk_import': True,
}

CONFIRM_BATCH = 8


class PetroleumLoadingsImportJob(models.Model):
    _name = 'petroleum.loadings.import.job'
    _description = 'Background Loadings Import Job'
    _order = 'id desc'

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company)
    auto_load = fields.Boolean(default=False)
    state = fields.Selection([
        ('pending', 'Running'),
        ('done', 'Done'),
    ], default='pending')
    queue_deal_ids = fields.Json(default=list)
    deal_ids = fields.Many2many('petroleum.deal')
    total_count = fields.Integer(default=0)
    confirmed_count = fields.Integer(default=0)
    loaded_count = fields.Integer(default=0)
    error_count = fields.Integer(default=0)
    error_log = fields.Text()
    result_html = fields.Html()

    def _kick(self):
        cron = self.env.ref(
            'petroleum_trading_desk.ir_cron_loadings_import',
            raise_if_not_found=False,
        )
        if cron:
            cron._trigger()

    @api.model
    def _cron_process_jobs(self):
        jobs = self.search([('state', '=', 'pending')], order='id')
        for job in jobs:
            job._process_batch()

    def _process_batch(self):
        self.ensure_one()
        queue = list(self.queue_deal_ids or [])
        if not queue:
            self._finish()
            return

        Deal = self.env['petroleum.deal'].with_company(self.company_id)
        batch = queue[:CONFIRM_BATCH]
        remaining = queue[CONFIRM_BATCH:]
        errors = []
        if self.error_log:
            try:
                errors = json.loads(self.error_log)
            except (json.JSONDecodeError, TypeError):
                errors = [str(self.error_log)]
        confirmed = self.confirmed_count
        loaded = self.loaded_count
        err_count = self.error_count

        for deal_id in batch:
            deal = Deal.with_context(**IMPORT_CTX).browse(deal_id)
            if not deal.exists() or deal.state != 'draft':
                continue
            try:
                with self.env.cr.savepoint():
                    deal.action_confirm()
                    confirmed += 1
                    if self.auto_load and 'NO INVOICE' not in (deal.notes or ''):
                        deal.action_load()
                        loaded += 1
            except Exception as exc:  # noqa: BLE001
                err_count += 1
                msg = _('Deal %s (row note: %s): %s') % (
                    deal.name, (deal.notes or '')[:40], exc)
                errors.append(msg)
                _logger.exception('Loadings import job failed on deal %s', deal_id)

        self.write({
            'queue_deal_ids': remaining,
            'confirmed_count': confirmed,
            'loaded_count': loaded,
            'error_count': err_count,
            'error_log': json.dumps(errors[-100:]),
        })

        if not remaining:
            self._finish(errors)

    # ------------------------------------------------------------------
    # Reseed + Retry (called when position lines were missing at import time)
    # ------------------------------------------------------------------
    def action_reseed_and_retry(self):
        """Seed daily position lines from the existing deal line data, then
        re-queue all still-draft deals from this job for background confirmation.

        Use this when the import ran before ``seed_daily_position`` was
        deployed (so no position lines were created) and all deals failed the
        confirmation step with "No daily position" errors.
        """
        self.ensure_one()
        draft_deals = self.deal_ids.filtered(lambda d: d.state == 'draft')
        if not draft_deals:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Nothing to retry'),
                    'message': _('No draft deals remain in this job.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        PositionLine = self.env['petroleum.daily.position.line'].with_company(
            self.company_id)

        # ── 1. Bucket deal-line quantities by (date, supplier, product) ──
        from collections import defaultdict
        buckets = defaultdict(lambda: {'qty': 0.0, 'buy_total': 0.0, 'buy_weight': 0.0})
        for deal in draft_deals:
            for line in deal.line_ids:
                if not line.supplier_id or not line.product_id:
                    continue
                key = (deal.date, line.supplier_id.id, line.product_id.id)
                b = buckets[key]
                b['qty'] += line.quantity
                if line.buy_price:
                    b['buy_weight'] += line.quantity
                    b['buy_total'] += line.buy_price * line.quantity

        # ── 2. Create / update position lines ────────────────────────────
        created = updated = 0
        errors = []
        for (pos_date, supplier_id, product_id), data in sorted(buckets.items()):
            buy_price = (
                data['buy_total'] / data['buy_weight'] if data['buy_weight'] else 0.0
            )
            domain = [
                ('date', '=', pos_date),
                ('supplier_id', '=', supplier_id),
                ('product_id', '=', product_id),
                ('depot_id', '=', False),
                ('company_id', '=', self.company_id.id),
            ]
            pos_line = PositionLine.search(domain, limit=1)
            if pos_line:
                vals = {}
                if pos_line.qty_bought < data['qty']:
                    vals['qty_bought'] = data['qty']
                if buy_price and not pos_line.buy_price:
                    vals['buy_price'] = buy_price
                if vals:
                    pos_line.write(vals)
                    updated += 1
            else:
                pos_line = PositionLine.with_context(**IMPORT_CTX).create({
                    'date': pos_date,
                    'supplier_id': supplier_id,
                    'product_id': product_id,
                    'company_id': self.company_id.id,
                    'qty_opening': 0.0,
                    'qty_bought': data['qty'],
                    'buy_price': buy_price,
                    'note': _('Backfilled from import job retry.'),
                })
                created += 1
            try:
                if pos_line.buy_price and pos_line.qty_total > 0:
                    pos_line._sync_purchase_order_line()
            except Exception as exc:  # noqa: BLE001
                errors.append('%s: %s' % (pos_line.display_name, exc))
                _logger.warning('Reseed PO sync failed for %s: %s', pos_line, exc)

        # ── 3. Re-queue the draft deals ──────────────────────────────────
        queue_ids = draft_deals.ids
        self.write({
            'state': 'pending',
            'queue_deal_ids': queue_ids,
            'error_count': 0,
            'confirmed_count': 0,
            'error_log': json.dumps(errors[-100:]) if errors else '[]',
            'result_html': _(
                '<p>Reseeded <b>%d</b> position line(s) created, '
                '<b>%d</b> updated. Re-queued <b>%d</b> deal(s) for '
                'confirmation.</p>'
            ) % (created, updated, len(queue_ids)),
        })
        self._kick()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reseed complete'),
                'message': _(
                    '%d position line(s) created, %d updated. '
                    '%d deal(s) re-queued for background confirmation.'
                ) % (created, updated, len(queue_ids)),
                'type': 'success',
                'sticky': True,
            },
        }

    def _finish(self, errors=None):
        if errors is None:
            errors = []
            if self.error_log:
                try:
                    errors = json.loads(self.error_log)
                except (json.JSONDecodeError, TypeError):
                    errors = [str(self.error_log)]
        done = self.confirmed_count
        total = self.total_count
        html = (
            "<div><h3>Background confirmation finished</h3>"
            "<p>Confirmed <b>%d</b> of <b>%d</b> deals. "
            "Loaded/invoiced: <b>%d</b>. Errors: <b>%d</b>.</p>"
        ) % (done, total, self.loaded_count, self.error_count)
        if errors:
            html += "<ul>" + ''.join(
                "<li>%s</li>" % e for e in errors[:20]) + "</ul>"
        html += "</div>"
        self.write({'state': 'done', 'result_html': html})
