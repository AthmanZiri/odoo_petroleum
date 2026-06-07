# -*- coding: utf-8 -*-
from itertools import groupby

from odoo import models
from odoo.exceptions import UserError
from odoo.tools.translate import _


class PetroleumDeal(models.Model):
    _inherit = 'petroleum.deal'

    def _whatsapp_proforma_attachment(self):
        self.ensure_one()
        report = self.env.ref('petroleum_trading_desk.action_report_deal_proforma')
        pdf_content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
            report.report_name, res_ids=self.ids)
        filename = '%s_proforma.pdf' % (self.name or 'deal').replace('/', '_')
        return self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'raw': pdf_content,
            'res_model': 'petroleum.deal',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

    def _whatsapp_compose_action(self, message):
        self.ensure_one()
        compose_form_id = self.env.ref(
            'whatsapp_mail_messaging.whatsapp_send_message_view_form').id
        partner = self.partner_id
        attachment = self._whatsapp_proforma_attachment()
        ctx = dict(self.env.context)
        ctx.update({
            'default_message': message,
            'default_partner_id': partner.id,
            'default_mobile': partner.phone,
            'default_image_1920': partner.image_1920,
            'default_res_model': 'petroleum.deal',
            'default_res_id': self.id,
            'default_deal_ids': str(self.id),
            'default_attachment_ids': [(6, 0, attachment.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'whatsapp.send.message',
            'views': [(compose_form_id, 'form')],
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
        }

    def _whatsapp_default_message(self):
        self.ensure_one()
        products = self.grade_display or _('fuel products')
        qty = int(self.total_qty) if self.total_qty else 0
        return (
            f"Hi {self.partner_id.name},\n"
            f"Your proforma {self.name} for {products} "
            f"({qty} L) amounting "
            f"{self.amount_sell}{self.currency_id.symbol} "
            f"is ready for review. Do not hesitate to contact us if you "
            f"have any questions."
        )

    def action_send_whatsapp(self):
        self.ensure_one()
        message_template = self.company_id.whatsapp_message
        message = message_template or self._whatsapp_default_message()
        return self._whatsapp_compose_action(message)

    @staticmethod
    def check_customers(partner_ids):
        partners = groupby(partner_ids)
        return next(partners, True) and not next(partners, False)

    def action_whatsapp_multi(self):
        deal_ids = self.env['petroleum.deal'].browse(
            self.env.context.get('active_ids'))
        partner_ids = deal_ids.mapped('partner_id').ids
        if not self.check_customers(partner_ids):
            raise UserError(_(
                'It appears that you have selected deals from multiple '
                'customers. Please select deals from a single customer.'))
        deal_numbers = ', '.join(deal_ids.mapped('name'))
        partner = deal_ids[0].partner_id
        message = (
            f"Hi {partner.name},\n\n"
            f"Your deals:\n"
            f"{deal_numbers}\n\n"
            f"are ready for review. Do not hesitate to contact us if you "
            f"have any questions."
        )
        attachments = self.env['ir.attachment']
        for deal in deal_ids:
            attachments |= deal._whatsapp_proforma_attachment()
        compose_form_id = self.env.ref(
            'whatsapp_mail_messaging.whatsapp_send_message_view_form').id
        ctx = dict(self.env.context)
        ctx.update({
            'default_message': message,
            'default_partner_id': partner.id,
            'default_mobile': partner.phone,
            'default_image_1920': partner.image_1920,
            'default_res_model': 'petroleum.deal',
            'default_deal_ids': ','.join(str(deal_id) for deal_id in deal_ids.ids),
            'default_attachment_ids': [(6, 0, attachments.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'whatsapp.send.message',
            'views': [(compose_form_id, 'form')],
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
        }
