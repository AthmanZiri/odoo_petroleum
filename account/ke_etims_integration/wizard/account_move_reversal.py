

from odoo import models, fields


class AccountMoveReversal(models.TransientModel):
    _inherit = 'account.move.reversal'

    l10n_ke_reason_code_id = fields.Many2one(
        comodel_name='ke_etims_integration.code',
        domain="[('code_type', '=', '32')]",
        string="KRA Reason",
        help="Kenyan code for Credit Notes",
    )

    def _prepare_default_reversal(self, move):
        return {
            'l10n_ke_reason_code_id': self.l10n_ke_reason_code_id.id,
            **super()._prepare_default_reversal(move),
        }
