from odoo import http
from odoo.http import request
import json


class TripDashboardController(http.Controller):

    @http.route('/trip_management/dashboard_data', type='jsonrpc', auth='user')
    def get_dashboard_data(self):
        """Return dashboard data as JSON"""
        dashboard = request.env['trip.dashboard']
        return dashboard.get_dashboard_data()