import logging

_logger = logging.getLogger(__name__)

_SKIP_INVOICE_LINE_DISPLAY = ('line_section', 'line_subsection', 'line_note')


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['account.move.line'].search([
        ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
        ('product_id', '!=', False),
        ('display_type', 'not in', _SKIP_INVOICE_LINE_DISPLAY),
    ])
    if lines:
        lines._compute_petro_margin()
    moves = env['account.move'].search([
        ('move_type', 'in', ('out_invoice', 'out_refund')),
    ])
    if moves:
        moves._compute_petro_margin_total()
    _logger.info(
        'Recomputed petro margin on %s invoice line(s) and %s invoice(s)',
        len(lines), len(moves),
    )
