from odoo import fields, models


class TripManagement(models.Model):
    _inherit = 'trip.management'

    depot_id = fields.Many2one('petroleum.depot', string='Loading Depot')
    epra_no = fields.Char(string='EPRA No.')
    compartment_plan = fields.Char(
        string='Compartment Plan',
        help='Tanker compartment split for loading, e.g. "2:3:2:3".')

    def _check_truck_not_allocated(self):
        """Relaxed: a truck doing several loads is normal in brokerage.

        The base module hard-blocked confirming a trip whose truck was on
        another active trip. We keep only the informational chatter warning
        already posted in ``action_confirm`` and drop the hard error.
        """
        return True

    def action_confirm(self):
        res = super().action_confirm()
        for trip in self:
            if trip.purchase_order_id and (trip.epra_no or trip.compartment_plan or trip.depot_id):
                trip.purchase_order_id.write({
                    'epra_no': trip.epra_no or trip.purchase_order_id.epra_no,
                    'compartment_plan': trip.compartment_plan or trip.purchase_order_id.compartment_plan,
                    'depot_id': trip.depot_id.id or trip.purchase_order_id.depot_id.id,
                })
        return res
