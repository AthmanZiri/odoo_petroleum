from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    petro_import_batch = fields.Char(
        string='Petroleum Import Batch', index=True, copy=False,
        help='Tags journal entries / invoices created by the Petroleum Data Import '
             'wizard so a batch can be identified and rolled back.')

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        posted._petro_auto_offset_moves()
        return posted

    def _petro_auto_offset_moves(self):
        """FIFO-offset open AR/AP for partners on these posted moves."""
        if (
            self.env.context.get('petro_skip_auto_offset')
            or self.env.context.get('petro_bulk_import')
            or self.env.context.get('petro_auto_offset_running')
        ):
            return
        moves = self.filtered(lambda move: move.state == 'posted')
        if not moves:
            return
        Line = self.env['account.move.line']
        for company, company_moves in moves.grouped('company_id').items():
            partner_ids = company_moves.line_ids.filtered(
                lambda line: line.account_id.account_type in (
                    'asset_receivable', 'liability_payable',
                ) and line.partner_id
            ).mapped('partner_id').ids
            if not partner_ids:
                continue
            Line._petro_fifo_offset(company, partner_ids=partner_ids)
