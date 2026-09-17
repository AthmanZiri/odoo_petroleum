import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Fill the new desk date on documents that already belong to a deal.

    The stored field is computed while the module loads, which happens before
    legacy sale/purchase invoices get their ``deal_id``. Linking them first and
    recomputing afterwards puts historical documents in the period of their
    deal instead of the period they were invoiced in.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['petroleum.deal'].backfill_move_deal_links()

    moves = env['account.move'].search([
        '|', ('deal_id', '!=', False),
        '|', ('petro_original_move_id.deal_id', '!=', False),
        ('reversed_entry_id.deal_id', '!=', False),
    ])
    if moves:
        moves._compute_petro_deal_date()
    _logger.info('Recomputed desk date on %s deal document(s)', len(moves))
