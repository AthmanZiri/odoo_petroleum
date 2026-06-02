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
