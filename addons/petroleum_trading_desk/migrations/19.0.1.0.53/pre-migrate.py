def migrate(cr, version):
    """Skip rewriting the loadings-import cron during this upgrade.

    The cron runs every minute. ir.cron.write() takes a row lock and raises
    while the job is executing, which aborts the module update. Marking the
    xml id noupdate before data files load makes Odoo leave the existing
    scheduled action alone. Fresh installs still create it from XML.
    """
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = TRUE
         WHERE module = 'petroleum_trading_desk'
           AND name = 'ir_cron_loadings_import'
        """
    )
