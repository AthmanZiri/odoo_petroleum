import logging
import re

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _statement_pdf_filename(self, report_data=None):
        self.ensure_one()
        if report_data and report_data.get('account_type') == 'liability_payable':
            label = 'Supplier'
        elif self.supplier_rank and not self.customer_rank:
            label = 'Supplier'
        else:
            label = 'Customer'
        safe = re.sub(r'[^\w\s-]', '', self.name or label).strip().replace(' ', '_')
        return 'Statement_%s.pdf' % (safe or label)

    def _statement_report_data(self, report_data):
        self.ensure_one()
        return dict(report_data, partner_ids=self.ids)

    def _render_statement_pdf(self, report_data):
        """Return (pdf_bytes, filename) for this partner's activity statement."""
        self.ensure_one()
        report = self.env.ref(
            'partner_statement.action_print_activity_statement',
            raise_if_not_found=False)
        if not report:
            return b'', self._statement_pdf_filename(report_data)
        data = self._statement_report_data(report_data)
        pdf_content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
            report.report_name, self.ids, data=data)
        return pdf_content, self._statement_pdf_filename(report_data)

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
        """Email this partner their activity statement PDF for the period."""
        self.ensure_one()
        if not self.email:
            return False
        is_vendor = report_data.get('account_type') == 'liability_payable'
        template_xmlid = (
            'petroleum_statement_mailer.mail_template_vendor_statement'
            if is_vendor else
            'petroleum_statement_mailer.mail_template_customer_statement'
        )
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
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

    def _statement_account_type(self):
        self.ensure_one()
        if self.supplier_rank and not self.customer_rank:
            return 'liability_payable'
        return 'asset_receivable'

    def action_send_statement_now(self):
        """Send a statement to the selected partner(s) from the contact form."""
        today = fields.Date.context_today(self)
        date_start = self.env['petroleum.statement.send']._default_date_start()
        for partner in self.filtered('email'):
            data = {
                'date_end': today,
                'date_start': date_start,
                'company_id': self.env.company.id,
                'show_aging_buckets': True,
                'show_only_overdue': False,
                'filter_non_due_partners': False,
                'account_type': partner._statement_account_type(),
                'aging_type': 'days',
                'filter_negative_balances': False,
                'excluded_accounts_ids': [],
                'is_activity': True,
            }
            partner._send_statement_email(date_start, today, data)
        return True
