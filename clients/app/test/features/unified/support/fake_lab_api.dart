import 'package:lab_inventory_client/models/lab_api_exception.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';

/// One recorded business call.
typedef LabCall = ({String path, Map<String, dynamic> params});

/// Explicit mock API used by every unified-feature test.
///
/// It plugs into the ONE injection point of production code
/// ([LabApiClient]'s `call` function), so the tests exercise the REAL payload
/// serialisation, the REAL response parsing and the REAL error propagation -
/// only the transport is faked. No test ever touches a server, and no test can
/// therefore be mistaken for real-stock acceptance.
class FakeLabApi {
  FakeLabApi({this.onCall});

  /// Handler invoked for every call. Throw [LabApiException] to simulate a
  /// business failure, or `StateError` for an unexpected endpoint.
  Future<Map<String, dynamic>> Function(String path, Map<String, dynamic> params)?
      onCall;

  final List<LabCall> calls = <LabCall>[];

  Future<Map<String, dynamic>> call(String path, Map<String, dynamic> params) {
    calls.add((path: path, params: params));
    final handler = onCall;
    if (handler == null) {
      throw StateError('FakeLabApi: unexpected call to $path (no handler installed)');
    }
    return handler(path, params);
  }

  LabApiClient get client => LabApiClient(call: call);

  List<LabCall> callsFor(String path) =>
      calls.where((call) => call.path == path).toList();

  int countFor(String path) => callsFor(path).length;

  Map<String, dynamic> onlyParams(String path) {
    final matches = callsFor(path);
    if (matches.length != 1) {
      throw StateError('expected exactly 1 call to $path, got ${matches.length}');
    }
    return matches.single.params;
  }

  /// Convenience: answer only the given paths with canned data.
  void answerWith(Map<String, Map<String, dynamic>> responses) {
    onCall = (path, params) async {
      final response = responses[path];
      if (response == null) {
        throw StateError('FakeLabApi: no canned response for $path');
      }
      return response;
    };
  }
}

/// Builds a list row in the exact shape of `/lab/api/catalog/search`.
Map<String, dynamic> itemJson({
  required String itemKey,
  String catalogCode = '',
  String name = '测试器件',
  String mpn = 'MPN-1',
  String brand = '品牌A',
  String package = '0805',
  int? categoryId,
  String categoryName = '电容',
  String? imageUrl,
  double labQuantity = 0,
  double? labAvailable,
  double? catalogStock,
  List<int> labTemplateIds = const <int>[],
  List<String> snCodes = const <String>[],
  List<Map<String, dynamic>> parameters = const <Map<String, dynamic>>[],
}) {
  return <String, dynamic>{
    'item_key': itemKey,
    'catalog_code': catalogCode,
    'name': name,
    'mpn': mpn,
    'brand': brand,
    'package': package,
    'category_id': categoryId,
    'category_name': categoryName,
    'image_url': imageUrl,
    'lab_quantity': labQuantity,
    'lab_available_quantity': labAvailable ?? labQuantity,
    'has_stock': labQuantity > 0,
    'catalog_stock': catalogStock,
    'lab_template_ids': labTemplateIds,
    'sn_codes': snCodes,
    'parameters': parameters,
    'revision': 'rev-1',
  };
}

/// Standard labelled response envelope helpers, for failure simulation.
LabApiException businessFailure(
  String code,
  String message, {
  Map<String, dynamic> fields = const <String, dynamic>{},
}) {
  return LabApiException(code: code, message: message, fields: fields);
}
