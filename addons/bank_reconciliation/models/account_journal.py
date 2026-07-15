# -*- coding: utf-8 -*-
from odoo import _, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def action_open_reconcile(self):
        """Open bank reconciliation filtered to unmatched lines by default."""
        action = super().action_open_reconcile()
        if self.type in ('bank', 'cash') and isinstance(action, dict):
            ctx = dict(action.get('context') or {})
            ctx.setdefault('search_default_not_matched', True)
            action['context'] = ctx
        return action

    def action_open_to_check(self):
        """Bank cards: open statement lines flagged To Check / to review."""
        self.ensure_one()
        if self.type not in ('bank', 'cash'):
            return False
        action = self.action_open_reconcile()
        if isinstance(action, dict):
            ctx = dict(action.get('context') or {})
            ctx.pop('search_default_not_matched', None)
            ctx['search_default_to_check'] = True
            ctx['default_journal_id'] = self.id
            ctx['search_default_journal_id'] = self.id
            action['context'] = ctx
            action['name'] = _('To Review')
        return action

    def action_open_invalid_statements(self):
        """Open statement lines linked to incomplete/invalid statements."""
        self.ensure_one()
        action = self.action_open_reconcile()
        if isinstance(action, dict):
            ctx = dict(action.get('context') or {})
            ctx.pop('search_default_not_matched', None)
            ctx['search_default_invalid_statement'] = True
            ctx['default_journal_id'] = self.id
            ctx['search_default_journal_id'] = self.id
            action['context'] = ctx
            action['name'] = _('Invalid Statements')
        return action
