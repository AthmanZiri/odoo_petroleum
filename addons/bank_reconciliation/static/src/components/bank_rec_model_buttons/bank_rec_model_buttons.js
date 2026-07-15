/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Lightweight OWL widget: buttons for applicable reconciliation models.
 * Calls account.reconcile.model.trigger_reconciliation_model (LGPL reimplementation).
 */
export class BankRecModelButtons extends Component {
    static template = "bank_reconciliation.BankRecModelButtons";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ models: [], busy: false });
        onWillStart(() => this.loadModels());
        onWillUpdateProps(() => this.loadModels());
    }

    get statementLineId() {
        return this.props.record.resId;
    }

    async loadModels() {
        if (!this.statementLineId) {
            this.state.models = [];
            return;
        }
        const models = await this.orm.call(
            "account.bank.statement.line",
            "read",
            [[this.statementLineId]],
            { fields: ["available_reconcile_model_ids"] }
        );
        const ids = models?.[0]?.available_reconcile_model_ids || [];
        if (!ids.length) {
            this.state.models = [];
            return;
        }
        this.state.models = await this.orm.call(
            "account.reconcile.model",
            "read",
            [ids],
            { fields: ["id", "name"] }
        );
    }

    async onApply(modelId) {
        if (this.state.busy || !this.statementLineId) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call(
                "account.reconcile.model",
                "trigger_reconciliation_model",
                [[modelId], this.statementLineId]
            );
            await this.props.record.model.root.load();
            this.notification.add("Reconciliation model applied.", { type: "success" });
        } catch (error) {
            this.notification.add(error?.data?.message || error.message || "Failed to apply model", {
                type: "danger",
            });
        } finally {
            this.state.busy = false;
            await this.loadModels();
        }
    }
}

export const bankRecModelButtons = {
    component: BankRecModelButtons,
};

registry.category("fields").add("bank_rec_model_buttons", bankRecModelButtons);
