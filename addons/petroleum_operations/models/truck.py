from odoo import models


class Truck(models.Model):
    _inherit = 'truck.management'

    def _check_driver_assignment(self):
        """Relaxed: the same driver/truck recurs across many client loads.

        Overriding the base @api.constrains method without re-decorating it
        removes the hard 'driver already assigned' block while keeping the
        driver-history tracking in the base create/write.
        """
        return True
