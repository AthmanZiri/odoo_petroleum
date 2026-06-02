from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _compute_name(self):
        """ When importing eTIMS vendor bills, preserve imported fields. """
        not_ke_amls = self.filtered(lambda l: not l.move_id.l10n_ke_oscu_attachment_file)
        super(AccountMoveLine, not_ke_amls)._compute_name()

    def _compute_product_uom_id(self):
        not_ke_amls = self.filtered(lambda l: not l.move_id.l10n_ke_oscu_attachment_file)
        super(AccountMoveLine, not_ke_amls)._compute_product_uom_id()

    def _compute_price_unit(self):
        not_ke_amls = self.filtered(lambda l: not l.move_id.l10n_ke_oscu_attachment_file)
        super(AccountMoveLine, not_ke_amls)._compute_price_unit()

    def _compute_tax_ids(self):
        not_ke_amls = self.filtered(lambda l: not l.move_id.l10n_ke_oscu_attachment_file)
        super(AccountMoveLine, not_ke_amls)._compute_tax_ids()
