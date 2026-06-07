# -*- coding: utf-8 -*-
import urllib.parse

from odoo import fields, models


class WhatsappSendMessage(models.TransientModel):
    _inherit = 'whatsapp.send.message'

    res_model = fields.Char(string='Source Document Model')
    res_id = fields.Integer(string='Source Document ID')
    deal_ids = fields.Char(string='Deal IDs')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Attachments',
        help='Documents to download when sending via WhatsApp.',
    )

    def _post_deal_messages(self):
        self.ensure_one()
        if self.res_model != 'petroleum.deal':
            return
        deal_ids = [
            int(item) for item in (self.deal_ids or '').split(',') if item.isdigit()
        ]
        if not deal_ids and self.res_id:
            deal_ids = [self.res_id]
        for deal in self.env['petroleum.deal'].browse(deal_ids):
            attachments = self.attachment_ids.filtered(
                lambda attachment: (
                    attachment.res_model == 'petroleum.deal'
                    and attachment.res_id == deal.id
                )
            )
            deal.message_post(
                body=self.message,
                attachment_ids=attachments.ids,
            )

    def send_message(self):
        if not (self.message and self.mobile):
            return False

        self._post_deal_messages()

        if self.res_model != 'petroleum.deal' and self.partner_id:
            self.partner_id.message_post(body=self.message)

        params = urllib.parse.urlencode({
            'phone': self.mobile,
            'text': self.message,
            'attachment_ids': ','.join(str(item) for item in self.attachment_ids.ids),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/whatsapp_mail_messaging/send?%s' % params,
            'target': 'new',
        }
