import 'json_read.dart';

class PendingReceipt {
  const PendingReceipt({
    required this.id,
    required this.traceCode,
    required this.name,
    required this.state,
    required this.quantity,
    required this.selected,
    required this.raw,
  });

  final int id;
  final String traceCode;
  final String name;
  final String state;
  final double quantity;
  final bool selected;
  final Map<String, dynamic> raw;
  bool get isPending => state == 'pending';
  bool get isCancelled => state == 'cancelled';
  String get payload => 'LABB:$traceCode';
  String get status => switch (state) {
    'done' => '已入库',
    'cancelled' => '已取消',
    _ => '待入库',
  };

  factory PendingReceipt.fromJson(Map<String, dynamic> json) => PendingReceipt(
    id: firstInt(json, const ['id']) ?? 0,
    traceCode: firstString(json, const ['trace_code']) ?? '',
    name: firstString(json, const ['mpn', 'name']) ?? '',
    state: firstString(json, const ['state']) ?? 'pending',
    quantity: firstDouble(json, const ['quantity']) ?? 0,
    selected: json['selected'] == true,
    raw: json,
  );
}
