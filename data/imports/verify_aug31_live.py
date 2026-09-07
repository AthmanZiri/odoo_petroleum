# Piped into: odoo shell -d jameel_petroleum
from datetime import date

KEEP = date(2026, 9, 1)
LOCK = date(2026, 8, 31)
BATCH = 'PETRO-IMP-AUG31-2026'

def n(model, domain):
    return env[model].search_count(domain)

print('SEP_MOVES', n('account.move', [('date', '>=', KEEP), ('state', '=', 'posted')]))
print('SEP_DEALS', n('petroleum.deal', [('date', '>=', KEEP)]))
print('SEP_SO', n('sale.order', [('date_order', '>=', KEEP)]))
print('SEP_PO', n('purchase.order', [('date_order', '>=', KEEP)]))
print('SEP_POS', n('petroleum.daily.position.line', [('date', '>=', KEEP)]))
print('LOANS', n('petroleum.loan.issued', []))
print('BATCH_MOVES', n('account.move', [('ref', 'ilike', BATCH)]))
print('ADJ', n('account.move', [('ref', 'ilike', 'Excel close adjustment')]))

astro = env['res.partner'].search([('name', 'ilike', 'ASTROMILE')], limit=1)
if astro:
    bal = env['account.move.line'].search([
        ('partner_id', '=', astro.id),
        ('account_id.account_type', 'in', ('asset_receivable', 'liability_payable')),
        ('parent_state', '=', 'posted'),
        ('date', '<=', LOCK),
    ])
    print('ASTROMILE_31AUG', round(sum(bal.mapped('balance')), 2), astro.name)
print('DONE')
