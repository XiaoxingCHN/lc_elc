import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/odoo_client.dart';
import '../models/product.dart';
import 'auth_provider.dart';

/// Products list provider - fetches all products from Odoo
final productsProvider = FutureProvider<List<Product>>((ref) async {
  final auth = ref.watch(authProvider);

  if (!auth.isAuthenticated) {
    throw Exception('Not authenticated');
  }

  final client = ref.watch(odooClientProvider);

  try {
    // Fetch products with all relevant fields.
    //
    // NOTE: this is NOT the full catalogue. The domain is empty and the query is
    // capped at 1000 rows, so the list screen shows at most the first 1000
    // products in Odoo's default order. Server-side paging is not implemented;
    // the list screen's search box only filters these already-loaded rows.
    final records = await client.search_read(
      'product.template',
      [],
      [
        'id',
        'name',
        'default_code',
        'lab_sn',
        'lab_lcsc_code',
        'lab_mpn',
        'lab_brand',
        'lab_package',
        'lab_description',
        'lab_specifications',
        'lab_datasheet_url',
        'lab_source_url',
        'categ_id',
        'type',
        'image_1920',
        'qty_available',
        'active',
        'create_date',
        'write_date',
      ],
      limit: 1000,
    );

    return records
        .map((record) => Product.fromJson(record))
        .toList();
  } catch (e) {
    throw Exception('Failed to fetch products: $e');
  }
});

/// Single product detail provider
final productDetailProvider = FutureProvider.family<Product, int>((ref, productId) async {
  final auth = ref.watch(authProvider);

  if (!auth.isAuthenticated) {
    throw Exception('Not authenticated');
  }

  final client = ref.watch(odooClientProvider);

  try {
    final records = await client.read(
      'product.template',
      [productId],
      [
        'id',
        'name',
        'default_code',
        'lab_sn',
        'lab_lcsc_code',
        'lab_mpn',
        'lab_brand',
        'lab_package',
        'lab_description',
        'lab_specifications',
        'lab_datasheet_url',
        'lab_source_url',
        'categ_id',
        'type',
        'image_1920',
        'qty_available',
        'active',
        'create_date',
        'write_date',
      ],
    );

    if (records.isEmpty) {
      throw Exception('Product not found');
    }

    return Product.fromJson(records[0]);
  } catch (e) {
    throw Exception('Failed to fetch product: $e');
  }
});

/// Create new product state notifier
final createProductProvider = StateNotifierProvider<CreateProductNotifier, CreateProductState>((ref) {
  final client = ref.watch(odooClientProvider);
  return CreateProductNotifier(client);
});

class CreateProductState {
  final bool isCreating;
  final int? newProductId;
  final String? errorMessage;
  final String? successMessage;

  const CreateProductState({
    this.isCreating = false,
    this.newProductId,
    this.errorMessage,
    this.successMessage,
  });

  CreateProductState copyWith({
    bool? isCreating,
    int? newProductId,
    String? errorMessage,
    String? successMessage,
  }) {
    return CreateProductState(
      isCreating: isCreating ?? this.isCreating,
      newProductId: newProductId ?? this.newProductId,
      errorMessage: errorMessage ?? this.errorMessage,
      successMessage: successMessage ?? this.successMessage,
    );
  }
}

class CreateProductNotifier extends StateNotifier<CreateProductState> {
  final OdooClient _client;

  CreateProductNotifier(this._client) : super(const CreateProductState());

  Future<bool> createProduct({
    required String name,
    String? lab_lcsc_code,
    String? lab_mpn,
    String? lab_brand,
    String? lab_package,
    String? lab_description,
    String? lab_specifications,
    String? lab_datasheet_url,
    String? lab_source_url,
    int? categ_id,
  }) async {
    state = state.copyWith(isCreating: true, errorMessage: null);

    try {
      final values = <String, dynamic>{
        'name': name,
        'type': 'consu',
        'purchase_ok': false,
        'sale_ok': false,
      };

      // Add optional fields
      if (lab_lcsc_code != null && lab_lcsc_code.isNotEmpty) {
        values['lab_lcsc_code'] = lab_lcsc_code;
      }
      if (lab_mpn != null && lab_mpn.isNotEmpty) {
        values['lab_mpn'] = lab_mpn;
      }
      if (lab_brand != null && lab_brand.isNotEmpty) {
        values['lab_brand'] = lab_brand;
      }
      if (lab_package != null && lab_package.isNotEmpty) {
        values['lab_package'] = lab_package;
      }
      if (lab_description != null && lab_description.isNotEmpty) {
        values['lab_description'] = lab_description;
      }
      if (lab_specifications != null && lab_specifications.isNotEmpty) {
        values['lab_specifications'] = lab_specifications;
      }
      if (lab_datasheet_url != null && lab_datasheet_url.isNotEmpty) {
        values['lab_datasheet_url'] = lab_datasheet_url;
      }
      if (lab_source_url != null && lab_source_url.isNotEmpty) {
        values['lab_source_url'] = lab_source_url;
      }
      if (categ_id != null) {
        values['categ_id'] = categ_id;
      }

      // SN is auto-generated by Odoo default_get
      final productId = await _client.create('product.template', values);

      state = CreateProductState(
        isCreating: false,
        newProductId: productId,
        successMessage: 'Product created successfully (ID: $productId)',
      );

      return true;
    } catch (e) {
      state = CreateProductState(
        isCreating: false,
        errorMessage: 'Failed to create product: $e',
      );
      return false;
    }
  }

  void reset() {
    state = const CreateProductState();
  }
}

/// Update product state notifier
final updateProductProvider = StateNotifierProvider<UpdateProductNotifier, UpdateProductState>((ref) {
  final client = ref.watch(odooClientProvider);
  return UpdateProductNotifier(client);
});

class UpdateProductState {
  final bool isUpdating;
  final bool success;
  final String? errorMessage;

  const UpdateProductState({
    this.isUpdating = false,
    this.success = false,
    this.errorMessage,
  });

  UpdateProductState copyWith({
    bool? isUpdating,
    bool? success,
    String? errorMessage,
  }) {
    return UpdateProductState(
      isUpdating: isUpdating ?? this.isUpdating,
      success: success ?? this.success,
      errorMessage: errorMessage ?? this.errorMessage,
    );
  }
}

class UpdateProductNotifier extends StateNotifier<UpdateProductState> {
  final OdooClient _client;

  UpdateProductNotifier(this._client) : super(const UpdateProductState());

  Future<bool> updateProduct(
    int productId,
    Map<String, dynamic> values,
  ) async {
    state = state.copyWith(isUpdating: true, errorMessage: null);

    try {
      await _client.write('product.template', [productId], values);

      state = UpdateProductState(
        isUpdating: false,
        success: true,
      );

      return true;
    } catch (e) {
      state = UpdateProductState(
        isUpdating: false,
        errorMessage: 'Failed to update product: $e',
      );
      return false;
    }
  }

  void reset() {
    state = const UpdateProductState();
  }
}
