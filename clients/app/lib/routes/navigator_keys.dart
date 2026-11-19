import 'package:flutter/widgets.dart';

/// Navigator keys shared by the router and the route tables.
///
/// They live in their own file because `routes/app_router.dart` imports
/// `features/unified/unified_routes.dart`; if the key stayed in the former, the
/// latter would need a circular import to reference it.
///
/// **Why the operational routes need the root key.** `context.push` from a
/// widget inside a `StatefulShellRoute` branch pushes onto THAT BRANCH's
/// navigator, so the pushed page keeps the shell's section switcher and bottom
/// bar. 入库 / 领料 / 归还 / 标签 / 历史 are full-screen jobs, not sections - they
/// declare `parentNavigatorKey: rootNavigatorKey` so they always land on the
/// root navigator and cover the shell.
final GlobalKey<NavigatorState> rootNavigatorKey = GlobalKey<NavigatorState>();
