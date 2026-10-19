import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lab_inventory_client/widgets/lab_ui.dart';

void main() {
  Future<GoRouter> open(WidgetTester tester, String initial) async {
    final router = GoRouter(initialLocation: initial, routes: [
      GoRoute(path: '/catalog', builder: (context, state) => Scaffold(
        appBar: LabAppBar(title: const Text('仓库')),
        body: Text(state.uri.queryParameters['offline'] == '1' ? '离线仓库内容' : '仓库内容'))),
      GoRoute(path: '/receipt', builder: (context, state) => LabPageFrame(child: Scaffold(
        appBar: LabAppBar(title: const Text('入库'), fallbackLocation: '/catalog'),
        body: const Text('入库表单')))),
      GoRoute(path: '/detail', builder: (context, state) => LabPageFrame(
        fallbackLocation: '/catalog?offline=1', child: Scaffold(
        appBar: LabAppBar(title: const Text('离线详情'), fallbackLocation: '/catalog?offline=1'),
        body: const Text('缓存参数')))),
      GoRoute(path: '/login', builder: (context, state) => const Scaffold(body: Text('登录页'))),
    ]);
    await tester.pumpWidget(MaterialApp.router(theme: LabTheme.light, routerConfig: router,
      builder: (context, child) => DecoratedBox(decoration: LabTheme.background, child: child!)));
    await tester.pumpAndSettle();
    addTearDown(router.dispose);
    return router;
  }
  testWidgets('direct business link always has a visible return to warehouse', (tester) async {
    await open(tester, '/receipt');
    expect(find.byTooltip('返回'), findsOneWidget);
    await tester.tap(find.byTooltip('返回')); await tester.pumpAndSettle();
    expect(find.text('仓库内容'), findsOneWidget); expect(find.text('入库表单'), findsNothing);
  });
  testWidgets('normal push returns through existing history', (tester) async {
    final router = await open(tester, '/catalog');
    router.push('/receipt'); await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('返回')); await tester.pumpAndSettle();
    expect(find.text('仓库内容'), findsOneWidget);
  });
  testWidgets('offline detail returns to offline catalog, not a signed-in route', (tester) async {
    await open(tester, '/detail');
    await tester.tap(find.byTooltip('返回')); await tester.pumpAndSettle();
    expect(find.text('离线仓库内容'), findsOneWidget);
  });
  testWidgets('Android system Back on direct business link returns to warehouse', (tester) async {
    await open(tester, '/receipt');
    await tester.binding.handlePopRoute(); await tester.pumpAndSettle();
    expect(find.text('仓库内容'), findsOneWidget);
  });
  testWidgets('glass toolbar fits small screen and retains an accessible back control', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320,640));
    addTearDown(()=>tester.binding.setSurfaceSize(null));
    await open(tester, '/receipt');
    expect(find.byType(LabGlassSurface), findsOneWidget);
    expect(find.byTooltip('返回'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
