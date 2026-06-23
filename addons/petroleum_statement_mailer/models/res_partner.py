import logging
import re

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _statement_pdf_filename(self):
        self.ensure_one()
        safe = re.sub(r'[^\w\s-]', '', self.name or 'Customer').strip().replace(' ', '_')
        return 'Statement_%s.pdf' % (safe or 'Customer')

    def _statement_report_data(self, report_data):
        self.ensure_one()
        return dict(report_data, partner_ids=self.ids)

    def _render_statement_pdf(self, report_data):
        """Return (pdf_bytes, filename) for this customer's activity statement."""
        self.ensure_one()
        report = self.env.ref(
            'partner_statement.action_print_activity_statement',
            raise_if_not_found=False)
        if not report:
            return b'', self._statement_pdf_filename()
        data = self._statement_report_data(report_data)
        pdf_content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
            report.report_name, self.ids, data=data)
        return pdf_content, self._statement_pdf_filename()

    def action_preview_statement_html(self, report_data):
        """Open the activity statement in the browser (HTML preview)."""
        self.ensure_one()
        report = self.env.ref(
            'partner_statement.action_print_activity_statement_html',
            raise_if_not_found=False)
        if not report:
            return False
        data = self._statement_report_data(report_data)
        return report.report_action(self, data=data)

    def _send_statement_email(self, date_start, date_end, report_data):
        """Email this customer their activity statement PDF for the period."""
        self.ensure_one()
        if not self.email:
            return False
        template = self.env.ref(
            'petroleum_statement_mailer.mail_template_customer_statement',
            raise_if_not_found=False)
        if not template:
            return False

        pdf_content, filename = self._render_statement_pdf(report_data)
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'raw': pdf_content,
            'res_model': 'res.partner',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        template.send_mail(
            self.id,
            force_send=True,
            email_values={'attachment_ids': [(4, attachment.id)]},
        )
        return True

    def action_send_statement_now(self):
        """Send a statement to the selected partner(s) from the contact form."""
        today = fields.Date.context_today(self)
        date_start = self.env['petroleum.statement.send']._default_date_start()
        data = {
            'date_end': today,
            'date_start': date_start,
            'company_id': self.env.company.id,
            'show_aging_buckets': True,
            'show_only_overdue': False,
            'filter_non_due_partners': False,
            'account_type': 'asset_receivable',
            'aging_type': 'days',
            'filter_negative_balances': False,
            'excluded_accounts_ids': [],
            'is_activity': True,
        }
        for partner in self.filtered('email'):
            partner._send_statement_email(date_start, today, data)
        return True
