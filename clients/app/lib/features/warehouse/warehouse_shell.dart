import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../providers/auth_provider.dart';
import 'warehouse_section.dart';
import 'widgets/warehouse_section_switcher.dart';

/// The signed-in chrome: four sections with one switcher.
///
/// **Why a shell now.** The app used to land straight on the component library
/// and had no navigation chrome at all - `lab_ui.dart` even said so. That was
/// fine while the library WAS the product; once 入库 / 领料 / 归还 / 标签 / 历史
/// were added, everything either lived on the library page or was reachable only
/// by a button inside it. The operator asked for the work split by subject, so
/// the shell owns four sections and the switcher is the one way between them.
///
/// **What the shell does NOT do.** It never draws an app bar for a screen: each
/// screen keeps its own `LabAppBar` (with its own actions and its own back
/// behaviour), and the operational pages (`/receipt`, `/labels`, ...) stay
/// OUTSIDE the shell so they push full-screen with `LabPageFrame` exactly as
/// before. The shell only decides where the switcher sits and which branch is
/// on screen.
class WarehouseShell extends ConsumerWidget {
  const WarehouseShell({
    super.key,
    required this.navigationShell,
  });

  final StatefulNavigationShell navigationShell;

  /// Width at which the switcher moves from the bottom bar to the top.
  ///
  /// Matches the catalog's own desktop breakpoint (900) so the whole app flips
  /// between "desktop" and "phone" layout at one place.
  static const double wideBreakpoint = 900;

  WarehouseSection get _section =>
      WarehouseSection.values[navigationShell.currentIndex];

  void _select(WarehouseSection section) {
    // `initialLocation: true` when re-tapping the current section: the operator
    // expects a second tap on "仓位" to go back to the location LIST, not to
    // stay deep in one location's contents.
    navigationShell.goBranch(
      section.branchIndex,
      initialLocation: section == _section,
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // The read-only offline browser (`/catalog?offline=1`) lives in this shell
    // but has no session: offering "仓位" / "作业" there would lead a signed-out
    // visitor into routes the router then refuses. With no session the shell
    // renders the branch and nothing else.
    final signedIn = ref.watch(authProvider.select((auth) => auth.isAuthenticated));

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= wideBreakpoint;
        if (!signedIn) {
          return Scaffold(
            backgroundColor: Colors.transparent,
            body: navigationShell,
          );
        }
        final dropdown = warehouseSwitcherNeedsDropdown(context);
        final switcher = dropdown
            ? WarehouseSectionDropdown(value: _section, onChanged: _select)
            : WarehouseSectionSwitcher(value: _section, onChanged: _select);

        if (wide) {
          return Scaffold(
            backgroundColor: Colors.transparent,
            // The top bar belongs to the visible screen; the shell only adds the
            // switcher above the body so it never competes with the screen's own
            // actions. It stays COMPACT (not stretched): a full-width capsule
            // reads as a second toolbar stacked on the screen's own app bar,
            // which is what the first version looked like.
            body: SafeArea(
              bottom: false,
              child: Column(
                children: <Widget>[
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 520),
                        child: WarehouseSectionSwitcher(
                          value: _section,
                          onChanged: _select,
                          expanded: false,
                        ),
                      ),
                    ),
                  ),
                  Expanded(child: navigationShell),
                ],
              ),
            ),
          );
        }

        return Scaffold(
          backgroundColor: Colors.transparent,
          body: navigationShell,
          bottomNavigationBar: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(0, 4, 0, 4),
              child: switcher,
            ),
          ),
        );
      },
    );
  }
}
