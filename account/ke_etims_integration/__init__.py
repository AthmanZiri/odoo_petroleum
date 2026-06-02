
import logging

from . import models
from . import wizard


_logger = logging.getLogger(__name__)


def _post_init_hook(env):
    # Load UNSPSC codes via fast COPY SQL
    _load_unspsc_codes(env)
    _assign_codes_uom(env)

    # Activate Kenya-relevant UNSPSC codes (those ending in '00')
    env['product.unspsc.code'].flush_model()
    env.cr.execute('''
        UPDATE product_unspsc_code
           SET active = 'true'
         WHERE code ILIKE '%00'
    ''')
    env['product.unspsc.code'].invalidate_model()

    # Load eTIMS type on the tax for existing KE companies
    for company in env['res.company'].search([('chart_template', '=', 'ke')], order="parent_path"):
        _logger.info("Company %s already has the Kenyan localization installed, updating...", company.name)
        ChartTemplate = env['account.chart.template'].with_company(company)
        tax_types_to_load = {
            tax_xmlid: values
            for tax_xmlid, values in ChartTemplate._get_ke_account_tax_etims_type().items()
            if ChartTemplate.ref(tax_xmlid, raise_if_not_found=False)
        }
        ChartTemplate._load_data({
            'account.tax': tax_types_to_load,
        })

    # Change all OSCU codes ir.model.data to noupdate, so they only get updated through the cron
    xmls = env['ir.model.data'].search([('model', '=', 'ke_etims_integration.code')])
    xmls.write({'noupdate': True})


def _load_unspsc_codes(env):
    """Import UNSPSC CSV data using fast COPY SQL.

    Even with the faster CSVs, loading via ORM would take +30 seconds,
    while this COPY approach takes under 3 seconds.
    """
    from odoo import tools
    csv_path = 'ke_etims_integration/data/product.unspsc.code.csv'
    with tools.misc.file_open(csv_path, 'rb') as csv_file:
        csv_file.readline()  # Skip header
        env.cr.copy_expert(
            """COPY product_unspsc_code (code, name, applies_to, active)
               FROM STDIN WITH DELIMITER '|'""", csv_file)
    # Create xml_ids to allow referencing this data
    env.cr.execute(
        """INSERT INTO ir_model_data
           (name, res_id, module, model, noupdate)
           SELECT concat('unspsc_code_', code), id, 'ke_etims_integration', 'product.unspsc.code', 't'
           FROM product_unspsc_code""")


def _assign_codes_uom(env):
    """Assign UoM codes after the UNSPSC data is created."""
    from odoo import tools
    tools.convert.convert_file(
        env, 'ke_etims_integration', 'data/product_data.xml', None, mode='init')
