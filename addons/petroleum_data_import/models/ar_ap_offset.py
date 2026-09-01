import logging

from odoo import api, models
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

AR_AP_TYPES = ('asset_receivable', 'liability_payable')
SKIP_DISPLAY = ('line_section', 'line_subsection', 'line_note')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _petro_offset_context(self):
        return self.with_context(
            petro_skip_auto_offset=True,
            petro_auto_offset_running=True,
            tracking_disable=True,
            mail_notrack=True,
            mail_create_nosubscribe=True,
        )

    @api.model
    def _petro_open_aml_domain(
            self, company, account_types=None, partner_ids=None,
            only_imported=False):
        domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('account_id.reconcile', '=', True),
            ('account_id.account_type', 'in', account_types or AR_AP_TYPES),
            ('display_type', 'not in', SKIP_DISPLAY),
            ('partner_id', '!=', False),
            ('amount_residual', '!=', 0),
        ]
        if partner_ids:
            domain.append(('partner_id', 'in', list(partner_ids)))
        if only_imported:
            domain.append(('move_id.petro_import_batch', '!=', False))
        return domain

    @api.model
    def _petro_commercial_partner_ids(self, partners):
        """AML partner_id is already the commercial partner; expand anyway."""
        if not partners:
            return []
        commercials = partners.mapped('commercial_partner_id')
        return self.env['res.partner'].search([
            ('commercial_partner_id', 'in', commercials.ids),
        ]).mapped('commercial_partner_id').ids

    @staticmethod
    def _petro_simulate_fifo_pairs(positives, negatives):
        """Count FIFO pairings without writing reconciliations."""
        pos_left = {line.id: line.amount_residual for line in positives}
        pairs = 0
        for neg in negatives:
            neg_left = -neg.amount_residual
            for pos in positives:
                if neg_left <= 0:
                    break
                avail = pos_left.get(pos.id, 0.0)
                if avail <= 0:
                    continue
                take = min(avail, neg_left)
                pos_left[pos.id] = avail - take
                neg_left -= take
                pairs += 1
        return pairs

    def _petro_fifo_offset_group(self, dry_run=False):
        """Offset one account's open debit vs credit lines (FIFO by date, id)."""
        lines = self.filtered(
            lambda line: not line.reconciled
            and not float_is_zero(
                line.amount_residual,
                precision_rounding=line.company_currency_id.rounding,
            )
        )
        if not lines:
            return 0, []
        lines = lines.sorted(lambda line: (line.date, line.id))
        positives = lines.filtered(lambda line: line.amount_residual > 0)
        negatives = lines.filtered(lambda line: line.amount_residual < 0)
        if not positives or not negatives:
            return 0, []

        pairs = self._petro_simulate_fifo_pairs(positives, negatives)
        if dry_run or not pairs:
            return pairs, []

        offset_lines = (positives | negatives)._petro_offset_context()
        errors = []
        try:
            with self.env.cr.savepoint():
                offset_lines.reconcile()
            return pairs, errors
        except Exception as exc:  # noqa: BLE001
            _logger.info(
                'Bulk FIFO offset failed (%s); trying sequential pairs.', exc)

        applied = 0
        for neg in negatives:
            for pos in positives:
                pos.invalidate_recordset([
                    'amount_residual', 'amount_residual_currency', 'reconciled',
                ])
                neg.invalidate_recordset([
                    'amount_residual', 'amount_residual_currency', 'reconciled',
                ])
                if pos.reconciled or neg.reconciled:
                    continue
                rounding = pos.company_currency_id.rounding
                if float_compare(pos.amount_residual, 0.0, precision_rounding=rounding) <= 0:
                    continue
                if float_compare(neg.amount_residual, 0.0, precision_rounding=rounding) >= 0:
                    continue
                try:
                    with self.env.cr.savepoint():
                        (pos | neg)._petro_offset_context().reconcile()
                    applied += 1
                except Exception as exc:  # noqa: BLE001
                    label = '%s / %s: %s' % (
                        pos.partner_id.display_name,
                        pos.account_id.display_name,
                        exc,
                    )
                    errors.append(label)
                    _logger.exception('FIFO offset pair failed: %s', label)
        return applied, errors

    @api.model
    def _petro_fifo_offset(
            self, company, account_types=None, partner_ids=None,
            only_imported=False, dry_run=False, limit_partners=None):
        """FIFO-offset open AR/AP items. Returns a stats dict."""
        if self.env.context.get('petro_auto_offset_running'):
            return {
                'partners': 0, 'matches': 0, 'errors': [],
                'before': 0, 'after': 0,
            }

        domain = self._petro_open_aml_domain(
            company, account_types=account_types, partner_ids=partner_ids,
            only_imported=only_imported)
        before = self.search_count(domain)

        matches = 0
        errors = []
        in_batch = set()
        for partner, _account, amls in self._read_group(
            domain,
            groupby=['partner_id', 'account_id'],
            aggregates=['id:recordset'],
        ):
            if not partner:
                continue
            has_pos = any(line.amount_residual > 0 for line in amls)
            has_neg = any(line.amount_residual < 0 for line in amls)
            if not (has_pos and has_neg):
                continue
            if partner.id not in in_batch:
                if limit_partners and len(in_batch) >= limit_partners:
                    continue
                in_batch.add(partner.id)
            pair_count, group_errors = amls._petro_fifo_offset_group(dry_run=dry_run)
            matches += pair_count
            errors.extend(group_errors)

        after = self.search_count(domain) if not dry_run else before
        return {
            'partners': len(in_batch),
            'matches': matches,
            'errors': errors,
            'before': before,
            'after': after,
        }

    @api.model
    def _petro_cron_auto_offset(self, batch_size=80, company_ids=None):
        """Nightly/hourly catch-up: FIFO-offset partners that still have both sides open."""
        if company_ids:
            companies = self.env['res.company'].browse(company_ids)
        else:
            companies = self.env['res.company'].search([])
        for company in companies:
            self._petro_fifo_offset(
                company, limit_partners=batch_size)
        return True
