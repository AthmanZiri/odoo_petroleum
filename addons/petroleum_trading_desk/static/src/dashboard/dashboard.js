/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

const GRADE_LABELS = {
    PMS: "PMS (Petrol)",
    AGO: "AGO (Diesel)",
    IK: "IK (Kerosene)",
};

export class PetroleumDashboard extends Component {
    static template = "petroleum_trading_desk.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            data: null,
            loading: true,
            filterOptions: null,
            filters: {
                date_from: "",
                date_to: "",
                product_id: "",
                partner_id: "",
                supplier_id: "",
            },
        });
        this.marginChartRef = useRef("marginChart");
        this.volumeChartRef = useRef("volumeChart");
        this.charts = [];

        onWillStart(async () => {
            try {
                await loadBundle("web.chartjs_lib");
            } catch {
                // charts are best-effort; the rest of the dashboard still works
            }
            this.state.filterOptions = await this.orm.call(
                "petroleum.desk.dashboard",
                "get_filter_options",
                []
            );
            const defaults = this.state.filterOptions.defaults;
            this.state.filters.date_from = defaults.date_from;
            this.state.filters.date_to = defaults.date_to;
            await this.load();
        });
        onMounted(() => this.renderCharts());
        onWillUnmount(() => this.destroyCharts());
    }

    _filtersPayload() {
        const f = this.state.filters;
        return {
            date_from: f.date_from || false,
            date_to: f.date_to || false,
            product_id: f.product_id ? parseInt(f.product_id, 10) : false,
            partner_id: f.partner_id ? parseInt(f.partner_id, 10) : false,
            supplier_id: f.supplier_id ? parseInt(f.supplier_id, 10) : false,
        };
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "petroleum.desk.dashboard",
            "get_dashboard_data",
            [this._filtersPayload()]
        );
        this.state.loading = false;
        this.renderCharts();
    }

    onFilterChange(field, ev) {
        this.state.filters[field] = ev.target.value;
    }

    resetFilters() {
        const defaults = this.state.filterOptions.defaults;
        this.state.filters.date_from = defaults.date_from;
        this.state.filters.date_to = defaults.date_to;
        this.state.filters.product_id = "";
        this.state.filters.partner_id = "";
        this.state.filters.supplier_id = "";
        this.load();
    }

    destroyCharts() {
        this.charts.forEach((c) => c && c.destroy());
        this.charts = [];
    }

    renderCharts() {
        if (typeof Chart === "undefined" || !this.state.data) {
            return;
        }
        this.destroyCharts();
        const data = this.state.data.charts;

        if (this.marginChartRef.el) {
            this.charts.push(new Chart(this.marginChartRef.el, {
                type: "line",
                data: {
                    labels: data.margin_trend.labels,
                    datasets: [{
                        label: "Margin",
                        data: data.margin_trend.values,
                        borderColor: "#1f8a4c",
                        backgroundColor: "rgba(31,138,76,0.12)",
                        fill: true,
                        tension: 0.3,
                        pointRadius: 2,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true } },
                },
            }));
        }
        if (this.volumeChartRef.el) {
            this.charts.push(new Chart(this.volumeChartRef.el, {
                type: "doughnut",
                data: {
                    labels: data.volume.labels,
                    datasets: [{
                        data: data.volume.values,
                        backgroundColor: data.volume.colors,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: "bottom" } },
                },
            }));
        }
    }

    dealFilterDomain(extra = []) {
        const f = this.state.filters;
        const domain = [
            ["state", "!=", "cancel"],
            ["date", ">=", f.date_from],
            ["date", "<=", f.date_to],
            ...extra,
        ];
        if (f.partner_id) {
            domain.push(["partner_id", "=", parseInt(f.partner_id, 10)]);
        }
        if (f.product_id) {
            domain.push(["line_ids.product_id", "=", parseInt(f.product_id, 10)]);
        }
        if (f.supplier_id) {
            domain.push(["line_ids.supplier_id", "=", parseInt(f.supplier_id, 10)]);
        }
        return domain;
    }

    openDeals(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "petroleum.deal",
            domain,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            target: "current",
        });
    }

    openFilteredDeals() {
        this.openDeals(this.dealFilterDomain(), "Deals");
    }

    openDealsByGrade(grade) {
        const opts = this.state.filterOptions.products || [];
        const product = opts.find((p) => p.name.includes(grade));
        const domain = this.dealFilterDomain();
        if (product) {
            domain.push(["line_ids.product_id", "=", product.id]);
        }
        this.openDeals(domain, GRADE_LABELS[grade] + " Deals");
    }

    openDebtors() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Customers with Balance",
            res_model: "res.partner",
            domain: [["customer_rank", ">", 0], ["credit", ">", 0]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openPartner(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async sendStatements() {
        await this.action.doAction(
            "petroleum_statement_mailer.action_statement_send_wizard"
        );
    }
}

registry.category("actions").add("petroleum_desk_dashboard", PetroleumDashboard);
