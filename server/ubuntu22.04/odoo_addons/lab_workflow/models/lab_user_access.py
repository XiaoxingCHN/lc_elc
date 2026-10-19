from odoo import api, models


class LabUserAccessGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _get_view_group_hierarchy(self):
        # Keep the complete native hierarchy and its access checks. The scoped
        # user-form widget only filters presentation, never the groups payload.
        hierarchy = super()._get_view_group_hierarchy()
        visible = []
        for xmlid in ('lab_workflow.privilege_lab_inventory',
                      'website.res_groups_privilege_website'):
            privilege = self.env.ref(xmlid, raise_if_not_found=False)
            if privilege:
                visible.append(privilege.id)
        return dict(hierarchy, lab_visible_privilege_ids=visible)
