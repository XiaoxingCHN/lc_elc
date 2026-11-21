import 'package:flutter/material.dart';

/// The four top-level sections of the signed-in app.
///
/// Before this existed every signed-in entry landed on the component library and
/// the other flows were only reachable from a floating button or a detail page.
/// The operator asked for the work to be split by *what they are looking at*
/// (stock totals / where things physically are / the library itself / the
/// operations), so the shell owns exactly these four.
///
/// Order is the on-screen order and is deliberately stable: overview first
/// (what do I have), then locations (where is it), then the library (what is
/// it), then the operations (what do I do).
enum WarehouseSection {
  overview,
  locations,
  catalog,
  manage;

  /// Short label for the segmented switcher. Two characters each so four fit a
  /// 320 px phone without the row needing to scroll.
  String get label {
    switch (this) {
      case WarehouseSection.overview:
        return '库存';
      case WarehouseSection.locations:
        return '仓位';
      case WarehouseSection.catalog:
        return '器件库';
      case WarehouseSection.manage:
        return '作业';
    }
  }

  /// Longer label used by the rail / accessibility description.
  String get description {
    switch (this) {
      case WarehouseSection.overview:
        return '库存速览';
      case WarehouseSection.locations:
        return '仓位速览';
      case WarehouseSection.catalog:
        return '器件库';
      case WarehouseSection.manage:
        return '库存管理';
    }
  }

  IconData get icon {
    switch (this) {
      case WarehouseSection.overview:
        return Icons.insights_outlined;
      case WarehouseSection.locations:
        return Icons.warehouse_outlined;
      case WarehouseSection.catalog:
        return Icons.inventory_2_outlined;
      case WarehouseSection.manage:
        return Icons.handyman_outlined;
    }
  }

  /// Branch index this section occupies in the shell route.
  int get branchIndex => index;
}
