import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    stats = env['purchase.order']._petro_repair_vendor_bill_links()
    lines = env['purchase.order.line'].search([
        ('invoice_lines.move_id.petro_price_adjustment', '=', 'supplier_buy'),
    ])
    if lines:
        lines._compute_qty_invoiced()
    _logger.info(
        'Petroleum PO/bill repair: %s price refunds tagged, '
        '%s adjustment lines linked, %s orphan extra lines linked, '
        '%s draft bills for cancelled-only POs, %s PO lines recomputed',
        stats.get('price_refunds_tagged', 0),
        stats['adjustments_linked'],
        stats['orphan_lines_linked'],
        stats['draft_bills_created'],
        len(lines),
    )
