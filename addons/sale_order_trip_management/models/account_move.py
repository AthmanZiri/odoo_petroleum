from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'
    
    truck_id = fields.Many2one('truck.management', string='Truck', readonly=True)
    driver_id = fields.Many2one('res.partner', string='Driver', domain=[('is_driver', '=', True)], readonly=True)
    driver_name = fields.Char(string='Driver Name', readonly=True)
    driver_id_no = fields.Char(string='Driver ID', readonly=True)
    transporter_name = fields.Char(string='Transporter', readonly=True)
    
    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        for move in moves:
            if move.move_type == 'in_invoice':
                # Check if created from purchase order
                if move.purchase_id:
                    move._update_truck_details_from_po()
                # Check invoice lines for purchase order reference
                elif move.invoice_line_ids:
                    for line in move.invoice_line_ids:
                        if line.purchase_line_id and line.purchase_line_id.order_id:
                            move.purchase_id = line.purchase_line_id.order_id
                            move._update_truck_details_from_po()
                            break
        return moves
    
    def _update_truck_details_from_po(self):
        if self.purchase_id and self.purchase_id.truck_id:
            self.truck_id = self.purchase_id.truck_id
            self.driver_id = self.purchase_id.driver_id
            self.driver_name = self.purchase_id.driver_name
            self.driver_id_no = self.purchase_id.driver_id_no
            self.transporter_name = self.purchase_id.transporter_name