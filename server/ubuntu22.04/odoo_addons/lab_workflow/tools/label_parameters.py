"""Choose label-sized specifications; the complete record remains unchanged."""

from odoo.addons.lab_inventory.tools.param_search import key_parameter_dicts


def key_parameters(parameters):
    """Keep label output aligned with the shared parameter-selection rules."""
    return key_parameter_dicts(parameters)
