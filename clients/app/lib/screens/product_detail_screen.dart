import 'package:flutter/material.dart';

import '../features/unified/screens/unified_item_detail_screen.dart';

/// Compatibility route for a local material archive.
///
/// `/products/:id` identified a `product.template` row. The unified detail works
/// on the canonical identity instead, and an unbound local archive IS `lab:<id>`
/// per `business_api_contract.json`, so this route simply opens the unified
/// detail for that identity. Same screen, same data, one library.
class ProductDetailScreen extends StatelessWidget {
  const ProductDetailScreen({
    Key? key,
    required this.productId,
  }) : super(key: key);

  final int productId;

  @override
  Widget build(BuildContext context) =>
      UnifiedItemDetailScreen(itemKey: 'lab:$productId');
}
