# -*- coding: utf-8 -*-
from odoo import fields, models


class SelectionMessage(models.Model):
    _name = 'selection.message'
    _description = 'Selection Message'

    name = fields.Char(string="Name", help="Name of message template")
    message = fields.Text(string="Message", required=True, help="The message to send")
