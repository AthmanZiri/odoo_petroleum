import logging

_logger = logging.getLogger(__name__)

_SKIP_INVOICE_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


def migrate(cr, version):
    """Recompute margins after sell-price credit notes stopped double-counting.

    Posted customer invoices keep their original price, and the credit note
    carries the delta. Deal totals must be rebuilt so a revised sell price
    is not reduced a second time by that note.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['account.move.line'].search([
        ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
        ('move_id.state', '=', 'posted'),
        ('product_id', '!=', False),
        ('display_type', 'not in', _SKIP_INVOICE_LINE_DISPLAY),
    ])
    if lines:
        lines._compute_petro_margin()
    moves = lines.move_id
    if moves:
        moves._compute_petro_margin_total()
    deals = env['petroleum.deal'].search([])
    if deals:
        deals._compute_amounts()
    _logger.info(
        'Recomputed petro margin on %s customer line(s), %s document(s), '
        'and %s deal(s)',
        len(lines), len(moves), len(deals),
    )
