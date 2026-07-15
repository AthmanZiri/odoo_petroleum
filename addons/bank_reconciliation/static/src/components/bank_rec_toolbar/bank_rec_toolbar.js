/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Dialog } from "@web/core/dialog/dialog";

export class BankRecSearchDialog extends Component {
    static template = "bank_reconciliation.BankRecSearchDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        statementLineId: Number,
        onSelect: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ term: "", rows: [], loading: false });
        onWillStart(() => this.search());
    }

    async search() {
        this.state.loading = true;
        try {
            this.state.rows = await this.orm.call(
                "account.bank.statement.line",
                "bank_rec_search_move_lines",
                [this.props.statementLineId, this.state.term, 40]
            );
        } finally {
            this.state.loading = false;
        }
    }

    onSelect(row) {
        this.props.onSelect(row);
        this.props.close();
    }
}

export class BankRecToolbar extends Component {
    static template = "bank_reconciliation.BankRecToolbar";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({ summary: null });
        onWillStart(() => this.loadSummary());
        onWillUpdateProps(() => this.loadSummary());
    }

    get statementLineId() {
        return this.props.record.resId;
    }

    async loadSummary() {
        if (!this.statementLineId) {
            this.state.summary = null;
            return;
        }
        this.state.summary = await this.orm.call(
            "account.bank.statement.line",
            "bank_rec_get_statement_summary",
            [[this.statementLineId]]
        );
    }

    openSearch() {
        if (!this.statementLineId) {
            return;
        }
        this.dialog.add(BankRecSearchDialog, {
            statementLineId: this.statementLineId,
            onSelect: async (row) => {
                // Toggle into kit selection via lines_widget_json write
                const data = {
                    id: row.id,
                    name: row.name,
                    partner_name: row.partner,
                    amount_residual: row.amount_residual,
                    currency_symbol: row.currency,
                    move_name: row.move_name,
                    date: row.date,
                    account_name: row.account,
                };
                await this.orm.write("account.bank.statement.line", [this.statementLineId], {
                    lines_widget_json: JSON.stringify(data),
                });
                this.notification.add(`Selected: ${row.move_name}`, { type: "info" });
                await this.props.record.model.root.load();
                await this.loadSummary();
            },
        });
    }

    async suggestPartner() {
        if (!this.statementLineId) {
            return;
        }
        await this.orm.call(
            "account.bank.statement.line",
            "action_retrieve_partner",
            [[this.statementLineId]]
        );
        await this.props.record.model.root.load();
        await this.loadSummary();
        this.notification.add("Partner suggestion applied if a unique match was found.", {
            type: "success",
        });
    }

    async quickCreate() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "Add a Transaction",
            res_model: "account.bank.statement.line",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_journal_id: this.props.record.data.journal_id?.[0]
                    || this.props.record.data.journal_id?.id,
            },
        });
    }
}

export const bankRecToolbar = {
    component: BankRecToolbar,
};

registry.category("fields").add("bank_rec_toolbar", bankRecToolbar);
