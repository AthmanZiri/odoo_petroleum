/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class TripDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            data: {},
            loading: true
        });
        
        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        try {
            this.state.loading = true;
            const data = await this.orm.call("trip.dashboard", "get_dashboard_data", []);
            this.state.data = data;
        } catch (error) {
            console.error("Error loading dashboard data:", error);
        } finally {
            this.state.loading = false;
        }
    }

    openTripsList(domain = []) {
        this.action.doAction({
            name: "Trips",
            type: "ir.actions.act_window",
            res_model: "trip.management",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current"
        });
    }

    openTrip(tripId) {
        this.action.doAction({
            name: "Trip",
            type: "ir.actions.act_window",
            res_model: "trip.management",
            res_id: tripId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current"
        });
    }

    getStateLabel(state) {
        const labels = {
            'draft': 'Draft',
            'confirmed': 'Confirmed',
            'in_progress': 'In Progress',
            'done': 'Done',
            'cancelled': 'Cancelled'
        };
        return labels[state] || state;
    }

    getStateClass(state) {
        const classes = {
            'draft': 'text-muted',
            'confirmed': 'text-info',
            'in_progress': 'text-warning',
            'done': 'text-success',
            'cancelled': 'text-danger'
        };
        return classes[state] || '';
    }

    getInvoiceStatusLabel(status) {
        const labels = {
            'no': 'Nothing to Invoice',
            'to invoice': 'To Invoice',
            'invoiced': 'Fully Invoiced'
        };
        return labels[status] || status;
    }

    getPaymentStatusLabel(status) {
        const labels = {
            'not_paid': 'Not Paid',
            'in_payment': 'In Payment',
            'paid': 'Paid'
        };
        return labels[status] || status;
    }

    getProgressBarClass(state) {
        const classes = {
            'draft': 'bg-secondary',
            'confirmed': 'bg-info',
            'in_progress': 'bg-warning',
            'done': 'bg-success',
            'cancelled': 'bg-danger'
        };
        return classes[state] || 'bg-secondary';
    }

    openFilteredTrips(filter) {
        let domain = [];
        switch(filter) {
            case 'active':
                domain = [['state', 'in', ['confirmed', 'in_progress']]];
                break;
            case 'completed':
                domain = [['state', '=', 'done']];
                break;
            case 'cancelled':
                domain = [['state', '=', 'cancelled']];
                break;
            case 'to_invoice':
                domain = [['invoice_status', '=', 'to invoice']];
                break;
            case 'not_paid':
                domain = [['payment_status', '=', 'not_paid']];
                break;
        }
        this.openTripsList(domain);
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(amount || 0);
    }

    getCompletionRate() {
        const total = this.state.data.total_trips || 0;
        const completed = this.state.data.completed_trips || 0;
        return total > 0 ? Math.round((completed / total) * 100) : 0;
    }
}

TripDashboard.template = "sale_order_trip_management.TripDashboard";

registry.category("actions").add("sale_order_trip_management.dashboard", TripDashboard);