# -*- coding: utf-8 -*-
import json
import urllib.parse

from odoo import http
from odoo.http import request


class WhatsappRedirect(http.Controller):

    @http.route('/whatsapp_mail_messaging/send', type='http', auth='user')
    def send(self, phone=None, text=None, attachment_ids=None, **kwargs):
        whatsapp_url = 'https://api.whatsapp.com/send?phone=%s&text=%s' % (
            phone or '',
            urllib.parse.quote(text or ''),
        )
        attachment_id_list = [
            int(item) for item in (attachment_ids or '').split(',') if item.isdigit()
        ]
        download_urls = [
            '/web/content/%s?download=true' % attachment_id
            for attachment_id in attachment_id_list
        ]
        payload = json.dumps({
            'whatsapp_url': whatsapp_url,
            'download_urls': download_urls,
        })
        html = """<!DOCTYPE html>
<html><head><title>WhatsApp</title></head>
<body>
<script>
const payload = %s;
window.open(payload.whatsapp_url, '_blank');
if (payload.download_urls.length) {
    payload.download_urls.forEach(function(url, index) {
        setTimeout(function() {
            const link = document.createElement('a');
            link.href = url;
            link.download = '';
            document.body.appendChild(link);
            link.click();
            link.remove();
        }, index * 400);
    });
}
setTimeout(function() { window.close(); }, 1500);
</script>
<p>Opening WhatsApp and downloading the proforma PDF...</p>
</body></html>""" % payload
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
