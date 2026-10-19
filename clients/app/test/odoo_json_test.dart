import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/models/odoo_json.dart';
import 'package:lab_inventory_client/models/product.dart';

/// These tests are offline: they need neither Flutter bindings nor an Odoo
/// server, and they cover the exact decoding defect that broke the copied
/// client - Odoo answers an empty field with `false`, not `null`.
void main() {
  group('odoo_json converters', () {
    test('odooString maps false/null to empty string', () {
      expect(odooString(false), '');
      expect(odooString(null), '');
      expect(odooString(''), '');
      expect(odooString('C123456'), 'C123456');
    });

    test('odooStringOrNull maps false/null/empty to null', () {
      expect(odooStringOrNull(false), isNull);
      expect(odooStringOrNull(null), isNull);
      expect(odooStringOrNull(''), isNull);
      expect(odooStringOrNull('KOA'), 'KOA');
    });

    test('odooBool PRESERVES a real false', () {
      // The whole point: a blanket "false means null" pass would turn an
      // archived product into an active one.
      expect(odooBool(false), isFalse);
      expect(odooBool(true), isTrue);
      expect(odooBool(null, fallback: true), isTrue);
      expect(odooBool('', fallback: true), isTrue);
      expect(odooBool('false'), isFalse);
      expect(odooBool(0), isFalse);
      expect(odooBool(1), isTrue);
    });

    test('odooDouble maps false/null to 0.0 and keeps ints as doubles', () {
      expect(odooDouble(false), 0.0);
      expect(odooDouble(null), 0.0);
      expect(odooDouble(12), 12.0);
      expect(odooDouble(1.5), 1.5);
      expect(odooDouble('2.25'), 2.25);
      expect(odooDouble('nonsense'), 0.0);
    });

    test('odooDateTimeOrNull parses Odoo timestamps and tolerates false', () {
      expect(odooDateTimeOrNull(false), isNull);
      expect(odooDateTimeOrNull(null), isNull);
      expect(odooDateTimeOrNull(''), isNull);
      expect(odooDateTimeOrNull('not-a-date'), isNull);
      // Odoo uses a space separator; Dart accepts it.
      expect(odooDateTimeOrNull('2026-10-12 10:00:00'), isNotNull);
      expect(odooDateTimeOrNull('2026-10-12T10:00:00'), isNotNull);
    });

    test('odooListOrNull maps a Many2one false to null', () {
      expect(odooListOrNull(false), isNull);
      expect(odooListOrNull(null), isNull);
      expect(odooListOrNull(<dynamic>[3, 'Resistors']), equals([3, 'Resistors']));
    });

    test('odooIntOrNull', () {
      expect(odooIntOrNull(false), isNull);
      expect(odooIntOrNull(7), 7);
      expect(odooIntOrNull('7'), 7);
      expect(odooIntOrNull('x'), isNull);
    });
  });

  group('Product.fromJson tolerates an all-empty Odoo record', () {
    test('decodes without throwing when every optional field is false', () {
      final json = <String, dynamic>{
        'id': 42,
        'name': 'Test resistor',
        'default_code': false,
        'lab_sn': false,
        'lab_lcsc_code': false,
        'lab_mpn': false,
        'lab_brand': false,
        'lab_package': false,
        'lab_description': false,
        'lab_specifications': false,
        'lab_datasheet_url': false,
        'lab_source_url': false,
        'categ_id': false,
        'type': 'consu',
        'image_1920': false,
        'qty_available': 12,
        'active': false,
        'create_date': false,
        'write_date': '2026-10-12 10:00:00',
      };

      final product = Product.fromJson(json);

      expect(product.id, 42);
      expect(product.name, 'Test resistor');
      expect(product.default_code, '');
      expect(product.lab_sn, '');
      expect(product.lab_lcsc_code, isNull);
      expect(product.lab_mpn, isNull);
      expect(product.categ_id, isNull);
      expect(product.image_1920, isNull);
      expect(product.qty_available, 12.0);
      expect(product.create_date, isNull);
      expect(product.write_date, isNotNull);
      // Must stay false - not be silently defaulted back to true.
      expect(product.active, isFalse);
    });

    test('decodes a fully populated record', () {
      final json = <String, dynamic>{
        'id': 7,
        'name': '10k 0603 resistor',
        'default_code': 'R-10K-0603',
        'lab_sn': 'LAB-000123',
        'lab_lcsc_code': 'C25804',
        'lab_mpn': 'RC0603FR-0710KL',
        'lab_brand': 'YAGEO',
        'lab_package': '0603',
        'lab_description': '厚膜电阻',
        'lab_specifications': '{"阻值":"10kΩ"}',
        'lab_datasheet_url': 'https://example.invalid/ds.pdf',
        'lab_source_url': 'https://item.szlcsc.com/123.html',
        'categ_id': <dynamic>[3, 'Resistors'],
        'type': 'consu',
        'image_1920': false,
        'qty_available': 1500,
        'active': true,
        'create_date': '2026-01-01 08:00:00',
        'write_date': '2026-10-12 10:00:00',
      };

      final product = Product.fromJson(json);

      expect(product.lab_sn, 'LAB-000123');
      expect(product.lab_lcsc_code, 'C25804');
      expect(product.categ_id, equals(<dynamic>[3, 'Resistors']));
      expect(product.active, isTrue);
      expect(product.qty_available, 1500.0);
    });

    test('toSummary() carries the list-view fields', () {
      final product = Product.fromJson(<String, dynamic>{
        'id': 9,
        'name': 'Cap 100nF',
        'lab_sn': 'LAB-000009',
        'lab_lcsc_code': 'C14663',
        'qty_available': 250,
        'active': true,
      });

      final summary = product.toSummary();

      expect(summary.id, 9);
      expect(summary.name, 'Cap 100nF');
      expect(summary.lab_sn, 'LAB-000009');
      expect(summary.lab_lcsc_code, 'C14663');
      expect(summary.qty_available, 250.0);
    });
  });
}
