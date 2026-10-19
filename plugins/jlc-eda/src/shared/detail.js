/**
 * Normalize both real catalog-detail shapes and lab_workflow flat shapes.
 *
 * catalog detail uses raw search_read rows:
 *   bag.location_id = [id, name], bag.lot_id = [id, name]
 *   issue.bag_id = [id, trace_code], issue.borrower_id = [id, name]
 * lab_workflow returns flat integers plus location_path / trace_code / *_name.
 */

export function many2oneName(value) {
  if (Array.isArray(value)) return value.length > 1 ? String(value[1] ?? '') : '';
  if (value === null || value === undefined || typeof value === 'object') return '';
  return String(value);
}

export function bagLocationName(bag) {
  if (!bag) return '—';
  if (Array.isArray(bag.location_id)) return many2oneName(bag.location_id) || '—';
  return bag.location_path || bag.location_code || (bag.location_id ? String(bag.location_id) : '—');
}

/** Return available only when the server actually provided it. Never use on-hand as available. */
export function bagAvailableQuantity(bag) {
  if (!bag || bag.available_quantity === null || bag.available_quantity === undefined) return null;
  const value = Number(bag.available_quantity);
  return Number.isFinite(value) ? value : null;
}

export function bagLotName(bag) {
  if (!bag) return '';
  return bag.lot_name || many2oneName(bag.lot_id) || '';
}

export function issueBagName(issue) {
  if (!issue) return '—';
  if (Array.isArray(issue.bag_id)) return many2oneName(issue.bag_id) || '—';
  return issue.trace_code || (issue.bag_id ? String(issue.bag_id) : '—');
}

export function issueBorrowerName(issue) {
  if (!issue) return '—';
  if (Array.isArray(issue.borrower_id)) return many2oneName(issue.borrower_id) || '—';
  return issue.borrower_name || (issue.borrower_id ? String(issue.borrower_id) : '—');
}

export function locationSummary(location) {
  if (!location) return '—';
  const name = location.location || location.name || location.path || '—';
  if (location.available_quantity !== null && location.available_quantity !== undefined) {
    return name + '(可用 ' + location.available_quantity + ')';
  }
  if (location.quantity !== null && location.quantity !== undefined) {
    return name + '(在库 ' + location.quantity + ')';
  }
  return name;
}
