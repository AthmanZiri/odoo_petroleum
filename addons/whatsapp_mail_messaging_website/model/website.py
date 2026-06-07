# -*- coding: utf-8 -*-
from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    mobile_number = fields.Char(string='Mobile Number')
