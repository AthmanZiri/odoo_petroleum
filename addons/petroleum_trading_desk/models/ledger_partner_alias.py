from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PetroleumLedgerPartnerAlias(models.Model):
    _name = 'petroleum.ledger.partner.alias'
    _description = 'Ledger Partner Alias (Deal ↔ Import)'
    _order = 'deal_partner_id, ledger_partner_id, id'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True)
    active = fields.Boolean(default=True)
    role = fields.Selection(
        selection=[
            ('customer', 'Customer only'),
            ('vendor', 'Vendor only'),
            ('both', 'Customer and vendor'),
        ],
        required=True,
        default='both',
        help='Whether this alias applies when matching deal clients, deal '
             'suppliers, or both.',
    )
    deal_partner_id = fields.Many2one(
        'res.partner', required=True, string='Deal contact',
        domain="[('company_id', 'in', [False, company_id])]",
        help='Contact as used on Trading Desk deals (e.g. WBP INV). '
             'Matching still requires the deal to use this contact or a child '
             'of its commercial partner in Odoo.',
    )
    ledger_partner_id = fields.Many2one(
        'res.partner', required=True, string='Ledger contact',
        domain="[('company_id', 'in', [False, company_id])]",
        help='Contact on imported invoices/bills when the import name differs '
             '(e.g. WBP INVEST.).',
    )
    notes = fields.Char()
    display_name = fields.Char(compute='_compute_display_name')

    _sql_constraints = [
        (
            'deal_ledger_partner_uniq',
            'unique(company_id, deal_partner_id, ledger_partner_id, role)',
            'This alias already exists for this company.',
        ),
    ]

    @api.depends('deal_partner_id', 'ledger_partner_id', 'role')
    def _compute_display_name(self):
        role_labels = dict(self._fields['role'].selection)
        for rec in self:
            rec.display_name = '%s → %s (%s)' % (
                rec.deal_partner_id.display_name or '?',
                rec.ledger_partner_id.display_name or '?',
                role_labels.get(rec.role, rec.role),
            )

    @api.constrains('deal_partner_id', 'ledger_partner_id')
    def _check_partners(self):
        Partner = self.env['res.partner']
        for rec in self:
            deal_cp = rec.deal_partner_id.commercial_partner_id
            ledger_cp = rec.ledger_partner_id.commercial_partner_id
            if deal_cp == ledger_cp:
                raise ValidationError(_(
                    'Deal contact and ledger contact must be different '
                    'commercial partners.'
                ))
            if ledger_cp.id in Partner.search(
                    [('id', 'child_of', deal_cp.id)]).ids:
                raise ValidationError(_(
                    '“%(ledger)s” is already under “%(deal)s” in Odoo’s contact '
                    'hierarchy. An alias is not needed — linking will match '
                    'via the partner tree.',
                    ledger=ledger_cp.display_name,
                    deal=deal_cp.display_name,
                ))

    @api.model
    def _partner_tree_ids(self, partner):
        """All partner ids in the commercial partner subtree (strict Odoo tree)."""
        if not partner:
            return []
        cp = partner.commercial_partner_id
        return self.env['res.partner'].search([('id', 'child_of', cp.id)]).ids

    @api.model
    def ledger_partner_match_ids(self, company, partner, role='customer', use_aliases=True):
        """Partner ids accepted on account.move for ledger matching."""
        if not partner:
            return []
        ids = set(self._partner_tree_ids(partner))
        if not use_aliases:
            return list(ids)

        cp = partner.commercial_partner_id
        domain = [
            ('company_id', '=', company.id),
            ('active', '=', True),
            ('deal_partner_id', 'child_of', cp.id),
        ]
        if role == 'customer':
            domain.append(('role', 'in', ('customer', 'both')))
        elif role == 'vendor':
            domain.append(('role', 'in', ('vendor', 'both')))
        for alias in self.search(domain):
            ids.update(self._partner_tree_ids(alias.ledger_partner_id))
        return list(ids)
