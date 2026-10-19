import 'package:flutter/material.dart';

import '../features/unified/screens/unified_catalog_screen.dart';

/// Compatibility route for the retired second library.
///
/// `/products` used to render its own list of `product.template` rows, capped at
/// the first 1000 records with client-side filtering. That parallel "internal
/// stock library" is retired by the accepted design: the app has exactly ONE
/// unified library. This route now shows the same screen as `/catalog`, so a
/// stale deep link, a bookmark or the old home button can never land the
/// operator in a different (and incomplete) list.
class ProductListScreen extends StatelessWidget {
  const ProductListScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) => const UnifiedCatalogScreen();
}
