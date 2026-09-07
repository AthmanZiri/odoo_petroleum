# Re-import August ledgers after payment-sign fix. Does not wipe September.
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
    'clean_existing': True,
})
env.cr.commit()
print('REIMPORT_START', flush=True)
result = wiz.action_import_sync()
print('IMPORT_COUNTERS', result['counters'], flush=True)
print('IMPORT_SECTIONS', result['sections'], flush=True)
print('IMPORT_ERRORS', len(result['errors']), flush=True)
for err in result['errors']:
    print('ERR', err, flush=True)
print('IMPORT_HTML_BEGIN', flush=True)
print(result['html'], flush=True)
print('IMPORT_HTML_END', flush=True)
