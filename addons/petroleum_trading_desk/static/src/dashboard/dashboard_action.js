/** @odoo-module **/

import { registry } from "@web/core/registry";
import { PetroleumDashboard } from "./dashboard";

registry.category("actions").add("petroleum_desk_dashboard", PetroleumDashboard);
