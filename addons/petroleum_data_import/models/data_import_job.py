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

SECTION_BATCH = 2


class PetroleumDataImportJob(models.Model):
    _name = 'petroleum.data.import.job'
    _description = 'Background Ledger Import Job'
    _order = 'id desc'

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True)
    batch_ref = fields.Char(required=True)
    cutoff_date = fields.Date(required=True)
    opening_date = fields.Date(required=True)
    sale_tax_id = fields.Many2one('account.tax')
    purchase_tax_id = fields.Many2one('account.tax')
    bank_journal_id = fields.Many2one('account.journal')
    misc_journal_id = fields.Many2one('account.journal')
    state = fields.Selection([
        ('pending', 'Running'),
        ('done', 'Done'),
    ], default='pending')
    queue_sections = fields.Json(default=list)
    total_sections = fields.Integer(default=0)
    processed_sections = fields.Integer(default=0)
    recon_data = fields.Json(default=list)
    counters = fields.Json(default=dict)
    result_html = fields.Html()
    error_log = fields.Text()

    def _kick(self):
        cron = self.env.ref(
            'petroleum_data_import.ir_cron_data_import',
            raise_if_not_found=False,
        )
        if cron:
            cron._trigger()

    @api.model
    def _cron_process_jobs(self):
        for job in self.search([('state', '=', 'pending')], order='id'):
            job._process_batch()

    def _wizard_vals(self):
        self.ensure_one()
        return {
            'company_id': self.company_id.id,
            'batch_ref': self.batch_ref,
            'cutoff_date': self.cutoff_date,
            'sale_tax_id': self.sale_tax_id.id,
            'purchase_tax_id': self.purchase_tax_id.id,
            'bank_journal_id': self.bank_journal_id.id,
            'misc_journal_id': self.misc_journal_id.id,
        }

    def _process_batch(self):
        self.ensure_one()
        queue = list(self.queue_sections or [])
        if not queue:
            self._finish()
            return

        Import = self.env['petroleum.data.import']
        wizard = Import.with_context(**IMPORT_CTX).new(self._wizard_vals())
        st = wizard._init_st()
        recon = list(self.recon_data or [])
        counters = dict(self.counters or {
            'opening': 0, 'invoice': 0, 'bill': 0, 'payment': 0,
        })
        errors = []
        if self.error_log:
            try:
                errors = json.loads(self.error_log)
            except (json.JSONDecodeError, TypeError):
                errors = [str(self.error_log)]

        batch = queue[:SECTION_BATCH]
        remaining = queue[SECTION_BATCH:]

        for item in batch:
            try:
                with self.env.cr.savepoint():
                    wizard._process_one_section(
                        st, item, self.opening_date, self.cutoff_date, recon)
            except Exception as exc:  # noqa: BLE001
                msg = '%s (%s): %s' % (item.get('name'), item.get('side'), exc)
                errors.append(msg)
                _logger.exception('Ledger import section failed: %s', msg)

        counters.update(st['counters'])
        self.write({
            'queue_sections': remaining,
            'processed_sections': self.processed_sections + len(batch),
            'recon_data': recon,
            'counters': counters,
            'error_log': json.dumps(errors[-100:]),
        })

        if not remaining:
            self._finish(errors)

    def _finish(self, errors=None):
        self.ensure_one()
        wizard = self.env['petroleum.data.import'].new(self._wizard_vals())
        recon_tuples = []
        for row in self.recon_data or []:
            partner = self.env['res.partner'].browse(row['partner_id'])
            account = self.env['account.account'].browse(row['account_id'])
            recon_tuples.append((
                row['name'], row['side'], row['wb_final'], partner, account))
        counters = self.counters or {}
        html = wizard._build_report(recon_tuples, counters)

        if errors is None:
            errors = []
            if self.error_log:
                try:
                    errors = json.loads(self.error_log)
                except (json.JSONDecodeError, TypeError):
                    errors = [str(self.error_log)]
        if errors:
            html += '<p><b>Section errors:</b></p><ul>'
            html += ''.join('<li>%s</li>' % e for e in errors[:20])
            html += '</ul>'

        self.write({'state': 'done', 'result_html': html})
        wizards = self.env['petroleum.data.import'].search([('job_id', '=', self.id)])
        if wizards:
            wizards.write({'state': 'done', 'result_html': html})
