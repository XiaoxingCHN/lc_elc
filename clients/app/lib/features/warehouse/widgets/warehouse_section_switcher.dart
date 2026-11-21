import 'package:flutter/material.dart';

import '../../../ui/glass/glass_controls.dart';
import '../warehouse_section.dart';

/// The four-section switcher, built on [GlassSegmentedControl].
///
/// Placement is the shell's job: on a desktop the shell puts this in the app
/// bar's `bottom`, on a phone in the bottom bar slot. The control itself is
/// identical in both places so the operator sees the same affordance everywhere
/// - only its position changes.
///
/// At 200 % text scaling the four two-character labels would still fit, but the
/// capsules would grow tall enough to eat the phone's bottom bar, so the shell
/// swaps this for [WarehouseSectionDropdown] above the same threshold the
/// receipt workspace already uses (16 px label scaled past 22 px).
class WarehouseSectionSwitcher extends StatelessWidget {
  const WarehouseSectionSwitcher({
    super.key,
    required this.value,
    required this.onChanged,
    this.expanded = true,
  });

  final WarehouseSection value;
  final ValueChanged<WarehouseSection> onChanged;

  /// True fills the available width (bottom bar); false sizes to the segments
  /// (the desktop top strip, where a full-width capsule reads as a second
  /// toolbar).
  final bool expanded;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: GlassSegmentedControl<WarehouseSection>(
        value: value,
        onChanged: onChanged,
        expanded: expanded,
        children: <WarehouseSection, Widget>{
          for (final section in WarehouseSection.values)
            section: Tooltip(
              message: section.description,
              child: Semantics(
                label: section.description,
                selected: section == value,
                // The two-character label is a visual shorthand; a screen
                // reader must hear the long name, so the inner Text's own
                // semantics are excluded rather than merged.
                excludeSemantics: true,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Icon(section.icon, size: 16),
                      const SizedBox(width: 6),
                      Text(section.label),
                    ],
                  ),
                ),
              ),
            ),
        },
      ),
    );
  }
}

/// Large-text fallback for [WarehouseSectionSwitcher].
class WarehouseSectionDropdown extends StatelessWidget {
  const WarehouseSectionDropdown({
    super.key,
    required this.value,
    required this.onChanged,
  });

  final WarehouseSection value;
  final ValueChanged<WarehouseSection> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: DropdownButtonFormField<WarehouseSection>(
        initialValue: value,
        isExpanded: true,
        decoration: const InputDecoration(
          isDense: true,
          labelText: '分区',
          prefixIcon: Icon(Icons.dashboard_outlined),
        ),
        items: <DropdownMenuItem<WarehouseSection>>[
          for (final section in WarehouseSection.values)
            DropdownMenuItem(
              value: section,
              child: Row(
                children: <Widget>[
                  Icon(section.icon, size: 18),
                  const SizedBox(width: 8),
                  Text(section.description),
                ],
              ),
            ),
        ],
        onChanged: (next) {
          if (next != null && next != value) onChanged(next);
        },
      ),
    );
  }
}

/// True when the section switcher must fall back to [WarehouseSectionDropdown].
///
/// Same rule (and same threshold) as the receipt workspace's step switcher: at
/// 200 % text the labels alone are fine, but the pills grow past the space a
/// phone bottom bar can spare.
bool warehouseSwitcherNeedsDropdown(BuildContext context) =>
    MediaQuery.textScalerOf(context).scale(16) > 22;
