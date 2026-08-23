from odoo import fields, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def _movement_quantity_after(self, counting_date):
        """Return the signed quantity moved on this quant after counting_date."""
        self.ensure_one()
        MoveLine = self.env["stock.move.line"]
        common_domain = [
            ("state", "=", "done"),
            ("date", ">", counting_date),
            ("product_id", "=", self.product_id.id),
            ("company_id", "=", self.company_id.id),
            ("lot_id", "=", self.lot_id.id or False),
            ("owner_id", "=", self.owner_id.id or False),
        ]
        incoming_domain = common_domain + [
            ("location_dest_id", "=", self.location_id.id),
            ("result_package_id", "=", self.package_id.id or False),
        ]
        outgoing_domain = common_domain + [
            ("location_id", "=", self.location_id.id),
            ("package_id", "=", self.package_id.id or False),
        ]
        # Move lines can use a different UoM; quants always use the product UoM.
        incoming = MoveLine._read_group(
            incoming_domain, [], ["quantity_product_uom:sum"]
        )[0][0]
        outgoing = MoveLine._read_group(
            outgoing_domain, [], ["quantity_product_uom:sum"]
        )[0][0]
        return incoming - outgoing

    def _prepare_backdated_inventory_quantities(self, counting_date):
        """Apply the count against stock at the historical counting date."""
        counting_date = fields.Datetime.to_datetime(counting_date)
        if not counting_date or counting_date >= fields.Datetime.now():
            return

        for quant in self.filtered("inventory_quantity_set"):
            quant.inventory_quantity += quant._movement_quantity_after(counting_date)

    def action_apply_inventory(self, date=None):
        if date:
            self._prepare_backdated_inventory_quantities(date)
        return super().action_apply_inventory(date)
