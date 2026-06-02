# Copyright 2024 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models


class DetailedActivityStatement(models.AbstractModel):
    """Enhanced Detailed Activity Statement with Trip Information"""

    _inherit = "report.partner_statement.detailed_activity_statement"

    def _get_account_display_lines(
        self, company_id, partner_ids, date_start, date_end, account_type
    ):
        # Use the enhanced activity statement method
        activity_statement = self.env["report.partner_statement.activity_statement"]
        return activity_statement._get_account_display_lines(
            company_id, partner_ids, date_start, date_end, account_type
        )