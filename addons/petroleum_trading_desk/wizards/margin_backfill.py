"""Backfill petro_buy_price on imported customer invoices from the loadings
Excel workbook.

The loadings report is the single authoritative source for agreed buy prices
per truck per loading date.  Customer invoices imported from the customer
ledger workbook carry only sell prices; their buy prices must be back-filled
so that ``petro_margin`` is computed correctly on each invoice line.

This wizard reads the same loadings workbook format used by the Loadings
Import wizard (two-row header, data from row 3, columns as below) and
matches each imported customer-invoice product line via:
    truck plate  ← narration of the invoice (HTML-stripped)
    loading date ← invoice_date
    grade        ← PMS / AGO / IK derived from product name / code

Column layout (1-based, same as PetroleumLoadingsImport.GRADES):
    1  = Loading date
    2  = Buy price PMS     3  = Sell price PMS
    4  = Buy price AGO     5  = Sell price AGO
    6  = Buy price IK      7  = Sell price IK
    8  = Supplier short name
    9  = Customer short name
    10 = Vehicle / truck plate
    11 = PMS qty   12 = AGO qty   13 = IK qty
"""
import base64
import io
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_SKIP = ('line_section', 'line_subsection', 'line_note')
_GRADES = ('PMS', 'AGO', 'IK')

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


def _strip_html(text):
    if not text:
        return ''
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', text)).strip()


def _grade_from_product(product):
    code = (product.default_code or '').upper()
    if code in _GRADES:
        return code
    name = (product.display_name or '').upper()
    for g in _GRADES:
        if g in name:
            return g
    return None


class PetroleumMarginBackfill(models.TransientModel):
    """Upload the loadings workbook and back-fill buy prices on invoices."""

    _name = 'petroleum.margin.backfill'
    _description = 'Backfill Invoice Buy Prices from Loadings Workbook'

    loadings_file = fields.Binary(
        string='Loadings Workbook (.xlsx)', required=True,
        help='Upload the same loadings Excel file used for the Loadings Import. '
             'Buy prices (columns B/D/F) will be matched to each imported '
             'customer invoice line and stored as the buy price for margin '
             'calculation.')
    loadings_filename = fields.Char()
    overwrite = fields.Boolean(
        string='Overwrite existing buy prices', default=True,
        help='Replace buy prices that were previously set (e.g. from vendor-bill '
             'matching) with the prices from the Excel loadings report.')
    result_html = fields.Html(readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft')

    # ------------------------------------------------------------------
    # Parsing helpers (same column layout as PetroleumLoadingsImport)
    # ------------------------------------------------------------------

    @staticmethod
    def _row_val(row, col, default=None):
        idx = col - 1
        if not row or idx >= len(row):
            return default
        return row[idx]

    def _parse_buy_prices(self, file_data):
        """Return dict: (date, truck_upper, grade_upper) → buy_price."""
        if not openpyxl:
            raise UserError(_('openpyxl is not installed on this server.'))

        wb = openpyxl.load_workbook(
            io.BytesIO(file_data), read_only=True, data_only=True)
        ws = wb.active
        row_iter = ws.iter_rows(min_row=1, max_col=17, values_only=True)

        # Skip two header rows
        try:
            next(row_iter)
            next(row_iter)
        except StopIteration:
            raise UserError(_('Workbook sheet is empty.')) from None

        import datetime

        buy_map = {}
        for row in row_iter:
            # Date (col 1)
            date_raw = self._row_val(row, 1)
            if isinstance(date_raw, datetime.datetime):
                date = date_raw.date()
            elif isinstance(date_raw, datetime.date):
                date = date_raw
            else:
                continue

            # Truck plate (col 10)
            truck_raw = self._row_val(row, 10)
            truck = str(truck_raw or '').strip()
            if not truck:
                continue

            # Handle combined plates like "KBK 733U/KCC 166U"
            plates = [p.strip().upper() for p in truck.replace('/', ',').split(',') if p.strip()]

            # Buy prices per grade (cols 2, 4, 6)
            grade_cols = [('PMS', 2), ('AGO', 4), ('IK', 6)]
            for grade, buy_col in grade_cols:
                buy_raw = self._row_val(row, buy_col)
                if buy_raw is None:
                    continue
                try:
                    buy_price = float(buy_raw)
                except (TypeError, ValueError):
                    continue
                if not buy_price:
                    continue
                for plate in plates:
                    key = (date, plate, grade)
                    if key not in buy_map:
                        buy_map[key] = buy_price

        wb.close()
        return buy_map

    # ------------------------------------------------------------------
    # Main action
    # ------------------------------------------------------------------

    def action_run(self):
        self.ensure_one()
        if not self.loadings_file:
            raise UserError(_('Please upload a loadings workbook.'))

        file_data = base64.b64decode(self.loadings_file)
        buy_map = self._parse_buy_prices(file_data)

        if not buy_map:
            raise UserError(_('No buy prices found in the workbook. '
                               'Please check the file format.'))

        # ── Find all posted imported customer invoices ─────────────────────
        invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('petro_import_batch', '!=', False),
        ])

        updated_lines = self.env['account.move.line']
        skipped = 0
        no_match = 0

        for inv in invoices:
            truck_raw = _strip_html(inv.narration)
            if not truck_raw:
                no_match += len(inv.invoice_line_ids.filtered(
                    lambda l: l.display_type not in _SKIP and l.product_id))
                continue

            # Handle combined plates in invoice narration too
            plates = [p.strip().upper() for p in truck_raw.replace('/', ',').split(',') if p.strip()]

            for line in inv.invoice_line_ids:
                if line.display_type in _SKIP or not line.product_id:
                    continue
                if not self.overwrite and line.petro_buy_price:
                    skipped += 1
                    continue

                grade = _grade_from_product(line.product_id)
                if not grade:
                    continue

                buy_price = None
                for plate in plates:
                    buy_price = buy_map.get((inv.invoice_date, plate, grade))
                    if buy_price is not None:
                        break

                if buy_price is not None:
                    line.petro_buy_price = buy_price
                    updated_lines |= line
                else:
                    no_match += 1

        # Recompute stored margins
        if updated_lines:
            updated_lines._compute_petro_margin()

        # Build summary
        total_margin = sum(updated_lines.mapped('petro_margin'))
        total_sell   = sum(updated_lines.mapped('price_subtotal'))
        margin_pct   = (total_margin / total_sell * 100) if total_sell else 0.0

        self.result_html = _(
            '<p>'
            'Updated buy price on <b>%(n)d</b> invoice line(s). '
            'Lines skipped (already had price): <b>%(skip)d</b>. '
            'Lines with no matching row in workbook: <b>%(nm)d</b>.'
            '</p>'
            '<p>'
            'Margin on updated lines: <b>KSh %(margin)s</b> '
            '(%(pct).1f %% of sell).'
            '</p>',
            n=len(updated_lines),
            skip=skipped,
            nm=no_match,
            margin=f'{total_margin:,.0f}',
            pct=margin_pct,
        )
        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
