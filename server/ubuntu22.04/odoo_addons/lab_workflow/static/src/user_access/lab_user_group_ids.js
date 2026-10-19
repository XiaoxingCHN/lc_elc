/** @odoo-module **/
import "@web/webclient/res_user_group_ids_field/res_user_group_ids_field";
import { registry } from "@web/core/registry";

const nativeField = registry.category("fields").get("res_user_group_ids");

export class LabUserGroupIdsField extends nativeField.component {
    getCategoryArch(category) {
        const hierarchy = this.props.record.data.view_group_hierarchy;
        const allowed = hierarchy.lab_visible_privilege_ids;
        if (this.props.record.resModel !== "res.users" || odoo.debug || !allowed?.length) {
            return super.getCategoryArch(category);
        }
        const visible = category.privileges.filter((privilege) => allowed.includes(privilege.id));
        return visible.length
            ? super.getCategoryArch({ ...category, privileges: visible })
            : "";
    }
}

// Inherit all native fields, values, write handling and security behavior.
// Hidden privileges remain in the native Record and are preserved on change.
registry.category("fields").add("lab_user_group_ids", {
    ...nativeField,
    component: LabUserGroupIdsField,
});
