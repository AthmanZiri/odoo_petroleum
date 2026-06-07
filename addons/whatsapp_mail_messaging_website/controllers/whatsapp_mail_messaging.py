# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class SendMessage(http.Controller):
    """Controller for website WhatsApp message templates."""

    @http.route('/whatsapp_message', type='json', auth='public')
    def whatsapp_message(self, **kwargs):
        messages = request.env['selection.message'].sudo().search_read(
            fields=['name', 'message'])
        return {'messages': messages}

    @http.route('/mobile_number', type='json', auth='public')
    def mobile_number(self, **kwargs):
        mobile_number = request.env['website'].sudo().search_read(
            fields=['mobile_number'])
        return {'mobile': mobile_number}
