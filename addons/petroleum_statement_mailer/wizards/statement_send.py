import io
import logging
import zipfile

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PetroleumStatementSend(models.TransientModel):
    _name = 'petroleum.statement.send'
    _description = 'Send Customer Statements'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    date_end = fields.Date(
        string='Statement Date', required=True,
        default=fields.Date.context_today)
    date_start = fields.Date(string='From', required=True)
    partner_ids = fields.Many2many(
        'res.partner', string='Customers', required=True,
        domain="[('customer_rank', '>', 0), ('parent_id', '=', False)]")
    only_with_balance = fields.Boolean(
        string='Only customers with a balance', default=True)
    only_with_email = fields.Boolean(
        string='Only customers with an email', default=True)

    recipient_count = fields.Integer(compute='_compute_counts')
    ready_count = fields.Integer(compute='_compute_counts')
    skipped_no_email = fields.Integer(compute='_compute_counts')

    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')
    result_html = fields.Html(readonly=True)

    @api.model
    def _default_date_start(self):
        today = fields.Date.context_today(self)
        return (today.replace(day=1) - relativedelta(days=1)).replace(day=1)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'date_start' not in res:
            res['date_start'] = self._default_date_start()
        if 'partner_ids' not in res:
            res['partner_ids'] = [(6, 0, self._recipient_ids(res).ids)]
        return res

    def _recipient_domain(self):
        domain = [
            ('customer_rank', '>', 0),
            ('parent_id', '=', False),
            ('company_id', 'in', [False, self.company_id.id]),
        ]
        if self.only_with_balance:
            domain.append(('credit', '>', 0))
        return domain

    @api.model
    def _recipient_ids(self, vals=None):
        vals = vals or {}
        company = self.env['res.company'].browse(
            vals.get('company_id') or self.env.company.id)
        Partner = self.env['res.partner'].with_company(company)
        domain = [
            ('customer_rank', '>', 0),
            ('parent_id', '=', False),
        ]
        if vals.get('only_with_balance', True):
            domain.append(('credit', '>', 0))
        partners = Partner.search(domain)
        if vals.get('only_with_email', True):
            partners = partners.filtered('email')
        return partners

    @api.depends('partner_ids', 'partner_ids.email')
    def _compute_counts(self):
        for wiz in self:
            wiz.recipient_count = len(wiz.partner_ids)
            ready = wiz.partner_ids.filtered('email')
            wiz.ready_count = len(ready)
            wiz.skipped_no_email = len(wiz.partner_ids - ready)

    @api.onchange('only_with_balance', 'only_with_email', 'company_id')
    def _onchange_filters(self):
        self.partner_ids = self._recipient_ids({
            'company_id': self.company_id.id,
            'only_with_balance': self.only_with_balance,
            'only_with_email': self.only_with_email,
        })

    def action_refresh_recipients(self):
        self.ensure_one()
        self.partner_ids = self._recipient_ids({
            'company_id': self.company_id.id,
            'only_with_balance': self.only_with_balance,
            'only_with_email': self.only_with_email,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _statement_data(self):
        self.ensure_one()
        return {
            'date_end': self.date_end,
            'date_start': self.date_start,
            'company_id': self.company_id.id,
            'show_aging_buckets': True,
            'show_only_overdue': False,
            'filter_non_due_partners': False,
            'account_type': 'asset_receivable',
            'aging_type': 'days',
            'filter_negative_balances': False,
            'excluded_accounts_ids': [],
            'is_activity': True,
        }

    def _validate(self):
        self.ensure_one()
        if not self.partner_ids:
            raise UserError(_('Select at least one customer.'))
        if self.date_start > self.date_end:
            raise UserError(_('The start date must be on or before the statement date.'))

    def _download_attachment(self, content, filename, mimetype):
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'raw': content,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': mimetype,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def action_download_pdf(self):
        """Download statement PDF for one customer, or a ZIP for several."""
        self.ensure_one()
        self._validate()
        report_data = self._statement_data()

        if len(self.partner_ids) == 1:
            pdf_content, filename = self.partner_ids._render_statement_pdf(report_data)
            return self._download_attachment(pdf_content, filename, 'application/pdf')

        buffer = io.BytesIO()
        used_names = set()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for partner in self.partner_ids:
                pdf_content, filename = partner._render_statement_pdf(report_data)
                if filename in used_names:
                    filename = filename.replace('.pdf', '_%s.pdf' % partner.id)
                used_names.add(filename)
                zf.writestr(filename, pdf_content)
        zip_name = 'Customer_Statements_%s.zip' % self.date_end.strftime('%Y-%m-%d')
        return self._download_attachment(
            buffer.getvalue(), zip_name, 'application/zip')

    def action_send(self):
        self.ensure_one()
        self._validate()
        to_send = self.partner_ids.filtered('email')
        skipped = self.partner_ids - to_send
        sent = 0
        errors = []

        for partner in to_send:
            try:
                partner._send_statement_email(
                    self.date_start, self.date_end, self._statement_data())
                sent += 1
            except Exception as exc:  # noqa: BLE001
                errors.append('%s: %s' % (partner.display_name, exc))
                _logger.exception('Statement email failed for %s', partner.display_name)

        html = (
            '<p>Statements sent to <b>%d</b> of <b>%d</b> selected customer(s).</p>'
            % (sent, len(self.partner_ids))
        )
        if skipped:
            html += '<p>Skipped (no email): %s</p>' % ', '.join(skipped.mapped('display_name'))
        if errors:
            html += '<p style="color:#c0392b"><b>Errors:</b><br/>%s</p>' % '<br/>'.join(errors[:20])

        self.write({'state': 'done', 'result_html': html})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
