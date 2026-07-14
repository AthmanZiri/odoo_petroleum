import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Community adaptation: Enterprise extends AccountMoveLineListRenderer from
 * account_accountant. Fall back to the standard list renderer so the journal
 * audit report still opens without that module.
 */
export class JournalReportAccountMoveLineReconcileListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.props.list.groups?.forEach(group => {
            group.list?.groups?.forEach(innerGroup => {
                this.toggleGroup(innerGroup);
            });
        });
    }
}

export const JournalReportAccountMoveLineReconcileLineListView = {
    ...listView,
    Renderer: JournalReportAccountMoveLineReconcileListRenderer,
};

registry.category("views").add("account_move_line_journal_report_list", JournalReportAccountMoveLineReconcileLineListView);
