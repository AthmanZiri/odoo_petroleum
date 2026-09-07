# Lock 31 Aug AR/AP to Excel BALANCE on the current database (no wipe).
import base64
import logging

logging.getLogger('odoo.addons.petroleum_data_import').setLevel(logging.INFO)

cust = open('/tmp/jameel_customers_aug2026.xlsx', 'rb').read()
supp = open('/tmp/jameel_suppliers_aug2026.xlsx', 'rb').read()

wiz = env['petroleum.data.import'].create({
    'cutoff_date': '2026-08-01',
    'customers_file': base64.b64encode(cust),
    'customers_filename': 'customers.xlsx',
    'suppliers_file': base64.b64encode(supp),
    'suppliers_filename': 'suppliers.xlsx',
    'batch_ref': 'PETRO-IMP-AUG31-2026',
    'clean_existing': False,
})
env.cr.commit()
queue = wiz._build_work_queue([
    (wiz.customers_file, 'ar'),
    (wiz.suppliers_file, 'ap'),
])
st = wiz.with_context(
    mail_create_nosubscribe=True, mail_notrack=True,
    tracking_disable=True, petro_bulk_import=True,
)._init_st()
recon = []
for item in queue:
    name = item['name']
    sec = item['section']
    side = sec['side']
    partner = wiz._get_partner(
        st, name, is_customer=(side == 'ar'), is_supplier=(side == 'ap'))
    account = (wiz._receivable_account(partner) if side == 'ar'
               else wiz._payable_account(partner))
    target = sec.get('last_balance')
    if target is None:
        target = sec['bf'] + sum(t['effect'] for t in sec['txns'])
    recon.append({
        'name': name, 'side': side, 'wb_final': target,
        'partner_id': partner.id, 'account_id': account.id,
    })
lock_date = wiz._lock_workbook_closes(st, recon)
env.cr.commit()
print('LOCK_DATE', lock_date, 'ADJUST', st['counters'].get('adjust'), flush=True)
html = wiz._build_report(
    [(r['name'], r['side'], r['wb_final'],
      env['res.partner'].browse(r['partner_id']),
      env['account.account'].browse(r['account_id'])) for r in recon],
    st['counters'], as_of=lock_date)
print(html, flush=True)
