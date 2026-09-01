from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _post_payments(self, to_process, edit_mode=False):
        # Register Payment reconciles selected invoices after posting. Skip the
        # FIFO hook during post so user allocations are not stolen, then offset
        # any leftover residual in _create_payments.
        self = self.with_context(petro_skip_auto_offset=True)
        return super()._post_payments(to_process, edit_mode=edit_mode)

    def _create_payments(self):
        payments = super()._create_payments()
        moves = payments.move_id.filtered(lambda move: move.state == 'posted')
        if moves:
            moves._petro_auto_offset_moves()
        return payments
