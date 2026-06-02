from odoo import models
from odoo.exceptions import AccessError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _allow_product_creation(self):
        """Allow system/data loads; restrict manual UI creation only."""
        if self.env.context.get("install_mode") or self.env.context.get("import_file"):
            return True
        return self.env.user.has_group(
            "restrict_product_creation.group_product_creator"
        )

    def create(self, vals_list):
        if not self._allow_product_creation():
            raise AccessError("Product creation is restricted.")
        return super().create(vals_list)
