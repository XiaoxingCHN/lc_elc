# -*- coding: utf-8 -*-
"""Shared, Odoo-free helpers for parameter keyword search.

The catalog importer runs outside Odoo and loads this file by path; the Odoo
models import it as ``odoo.addons.lab_inventory.tools.param_search``.  Keep it
free of ``odoo`` imports so both callers can use the same rules.
"""

import json
import re
import unicodedata

_SI = {
    'p': 1e-12,
    'n': 1e-9,
    'u': 1e-6,
    'µ': 1e-6,   # µ
    'μ': 1e-6,   # μ
    'm': 1e-3,
    'k': 1e3,
    'K': 1e3,
    'M': 1e6,
    'G': 1e9,
}

_NUM = r'([0-9]+(?:\.[0-9]+)?)'
_UNIT_OHM = r'(?:Ω|ohm|ohms|R|r)?'
_UNIT_FARAD = r'(?:F|f)?'
_UNIT_VOLT = r'(?:V|v)?'
_UNIT_WATT = r'(?:W|w)?'


def _text(value):
    if value is None:
        return ''
    return unicodedata.normalize('NFKC', str(value)).strip()


def _clean(value):
    return ' '.join(_text(value).split())


def _raw(value):
    """Keep the source spelling (only collapse whitespace)."""
    if value is None:
        return ''
    return ' '.join(str(value).split())


def _pair(entry):
    """Return ``(name, value)`` from dict / 2-tuple / import 4-tuple."""
    if isinstance(entry, dict):
        return _raw(entry.get('name')), _raw(entry.get('value'))
    if isinstance(entry, (list, tuple)):
        if len(entry) >= 4:                 # (code, name, value, detail)
            return _raw(entry[1]), _raw(entry[2])
        if len(entry) == 2:                 # (name, value)
            return _raw(entry[0]), _raw(entry[1])
        if len(entry) == 3:                 # (name, value, detail)
            return _raw(entry[0]), _raw(entry[1])
    return '', _raw(entry)


def key_pairs(parameters):
    """Select label-sized key parameters (same rules as label printing)."""
    pairs = []
    for entry in parameters or []:
        name, value = _pair(entry)
        if name or value:
            pairs.append((name, value))
    if any('阻值' in name for name, _value in pairs):
        keys = ('阻值', '精度', '功率')
    elif any(any(k in name for k in ('容值', '容量', '电容量'))
             for name, _value in pairs):
        keys = ('容值', '容量', '电容量', '耐压', '额定电压', '介质', '材质')
    else:
        return pairs[:3]
    return [(name, value) for name, value in pairs
            if any(key in name for key in keys)][:4]


def key_parameter_dicts(parameters):
    """Label-compatible wrapper: list of ``{'name': ..., 'value': ...}``."""
    return [{'name': name, 'value': value} for name, value in key_pairs(parameters)]


def _dedupe(tokens):
    seen = set()
    out = []
    for token in tokens:
        token = _raw(token)
        if not token:
            continue
        # Keep case and micro-sign variants: ILIKE is case-insensitive, and
        # NFKC query normalization maps µ to μ, so both spellings matter.
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plain(number):
    """Compact decimal without trailing zeros (10, 4.7, 0.1, 4700)."""
    return ('%.10f' % number).rstrip('0').rstrip('.')


def _r_notation(ohms):
    """Common resistor shorthand: 10R, 4R7, R1, 4k7, 1k5, 1M."""
    if ohms == 0:
        return ['0R', '0R0']
    if ohms >= 1e6:
        return ['%sM' % _plain(ohms / 1e6)]
    if ohms >= 1e3:
        text = _plain(ohms / 1e3)
        if '.' in text:
            whole, frac = text.split('.', 1)
            return ['%sk%s' % (whole, frac), '%sK%s' % (whole, frac), text + 'k']
        return [text + 'k', text + 'K']
    if ohms >= 1:
        text = _plain(ohms)
        if '.' in text:
            whole, frac = text.split('.', 1)
            return ['%sR%s' % (whole, frac), text + 'R']
        return [text + 'R']
    # Values below 1 ohm use R as the decimal point: R1 = 0.1, R01 = 0.01.
    digits = ('%.10f' % ohms).split('.', 1)[1].rstrip('0')
    if not digits:
        return ['R0']
    return ['R' + digits, '0R' + digits]


def _resistance_aliases(value):
    value = _clean(value)
    if not value:
        return []
    text = value.replace(' ', '')
    low = text.casefold()
    if low in ('-', '—', 'n/a', 'na'):
        return [value]

    # 4R7 / R1 / 10R / 1R0
    m = re.match(r'^([0-9]+)[rR]([0-9]+)$', text)
    if m:
        ohms = float('%s.%s' % (m.group(1), m.group(2)))
    else:
        m = re.match(r'^[rR]([0-9]+)$', text)
        if m:
            ohms = float('0.' + m.group(1))
        else:
            m = re.match(r'^([0-9]+(?:\.[0-9]+)?)[rR]$', text)
            if m:
                ohms = float(m.group(1))
            else:
                # 4k7 / 1k5 / 2M2: prefix letter acts as the decimal point.
                m = re.match(r'^([0-9]+)([kKmM])([0-9]+)$', text)
                if m:
                    ohms = (float('%s.%s' % (m.group(1), m.group(3)))
                            * _SI.get(m.group(2), 1.0))
                else:
                    m = re.match(r'^' + _NUM + r'\s*([pnuµμmkKMG]?)\s*' +
                                 _UNIT_OHM + r'$', text)
                    if not m:
                        return [value]
                    base = float(m.group(1))
                    prefix = m.group(2) or ''
                    ohms = base * _SI.get(prefix, 1.0) if prefix else base

    ohms = round(ohms, 12)
    aliases = [value]
    if ohms >= 1e6:
        human = '%sMΩ' % _plain(ohms / 1e6)
    elif ohms >= 1e3:
        human = '%skΩ' % _plain(ohms / 1e3)
    elif ohms >= 1:
        human = '%sΩ' % _plain(ohms)
    elif ohms >= 1e-3:
        human = '%smΩ' % _plain(ohms * 1e3)
    else:
        human = '%sΩ' % _plain(ohms)
    aliases.extend([human, human.replace('Ω', 'ohm'),
                    human.replace('Ω', 'ohms')])
    if ohms < 1 and ohms > 0:
        aliases.append('%sΩ' % _plain(ohms))
        aliases.append('%smΩ' % _plain(ohms * 1e3))
    aliases.extend(_r_notation(ohms))
    aliases.append(_plain(ohms))
    return _dedupe(aliases)


def _looks_resistance(value):
    text = _clean(value).replace(' ', '')
    if not text:
        return False
    if re.match(r'^(?:[0-9]+[rR][0-9]+|[rR][0-9]+|[0-9]+(?:\.[0-9]+)?[rR])$', text):
        return True
    if re.match(r'^[0-9]+[kKmM][0-9]+$', text):
        return True
    return bool(re.match(r'^' + _NUM + r'\s*[pnuµμmkKMG]?\s*' +
                         _UNIT_OHM + r'$', text))


def _capacitance_aliases(value):
    value = _clean(value)
    if not value:
        return []
    text = value.replace(' ', '')
    m = re.match(r'^' + _NUM + r'\s*([pnuµμm]?)\s*' + _UNIT_FARAD + r'$', text,
                 re.IGNORECASE)
    if not m:
        return [value]
    base = float(m.group(1))
    prefix = (m.group(2) or '').casefold()
    unit = 'F' if text[-1:].casefold() == 'f' else ''
    if not prefix and not unit:
        return [value]
    prefix = {'µ': 'u', 'μ': 'u'}.get(prefix, prefix)
    if prefix:
        farads = base * _SI.get(prefix, 1.0)
    else:
        farads = base
    if farads <= 0:
        return [value]
    aliases = [value]
    # Include every engineering unit that is still readable, so 100nF also
    # stores 0.1uF / 0.1µF and 470pF also stores 0.47nF.
    for prefix_name, scale, short in (('pF', 1e-12, 'p'),
                                      ('nF', 1e-9, 'n'),
                                      ('uF', 1e-6, 'u')):
        scaled = farads / scale
        if scaled >= 0.001:
            text2 = _plain(round(scaled, 12))
            aliases.extend([text2 + prefix_name, text2 + short])
            if prefix_name == 'uF':
                aliases.extend([text2 + 'µF', text2 + 'μF',
                                text2 + 'µ', text2 + 'μ'])
    # Always include the natural unit even when the value is < 1 in that unit.
    if farads < 1e-9:
        scaled = farads / 1e-12
        aliases.extend(['%spF' % _plain(scaled), '%sp' % _plain(scaled)])
    elif farads < 1e-6:
        scaled = farads / 1e-9
        aliases.extend(['%snF' % _plain(scaled), '%sn' % _plain(scaled)])
    else:
        scaled = farads / 1e-6
        aliases.extend(['%suF' % _plain(scaled), '%su' % _plain(scaled)])
    # Query-friendly ASCII/µ variants for the original prefix.
    if 'u' in text.casefold() or 'µ' in text or 'μ' in text:
        aliases.append(text.replace('µ', 'u').replace('μ', 'u'))
    return _dedupe(aliases)


def _looks_capacitance(value):
    text = _clean(value).replace(' ', '')
    return bool(re.match(r'^' + _NUM + r'\s*[pnuµμm]?\s*' + _UNIT_FARAD + r'$',
                         text, re.IGNORECASE))


def _tolerance_aliases(value):
    value = _clean(value)
    if not value:
        return []
    aliases = [value]
    stripped = value[1:].strip() if value.startswith('±') else value
    if stripped != value:
        aliases.append(stripped)
    # Only simple tolerances get a ± variant / numeric token.  Range values
    # such as -20%~+80% must stay intact.
    simple = re.match(r'^[0-9]+(?:\.[0-9]+)?\s*(?:%|°C|℃)$', stripped)
    if simple:
        if not value.startswith('±'):
            aliases.append('±' + stripped)
        aliases.append(re.sub(r'(?:%|°C|℃)$', '', stripped).strip())
    return _dedupe(aliases)


def _voltage_aliases(value):
    value = _clean(value)
    if not value:
        return []
    text = value.replace(' ', '')
    m = re.match(r'^' + _NUM + r'\s*([kKmM]?)\s*' + _UNIT_VOLT + r'$', text)
    if not m:
        return [value]
    base = float(m.group(1))
    prefix = m.group(2) or ''
    volts = base * _SI.get(prefix, 1.0) if prefix else base
    aliases = [value, _plain(volts), '%sV' % _plain(volts)]
    if volts >= 1000:
        aliases.extend(['%skV' % _plain(volts / 1000.0),
                        '%sk' % _plain(volts / 1000.0)])
    return _dedupe(aliases)


def _looks_voltage(value):
    return bool(re.match(r'^' + _NUM + r'\s*[kKmM]?\s*' + _UNIT_VOLT + r'$',
                         _clean(value).replace(' ', '')))


def _power_aliases(value):
    value = _clean(value)
    if not value:
        return []
    text = value.replace(' ', '')
    m = re.match(r'^' + _NUM + r'\s*([pnuµμmkKMG]?)\s*' + _UNIT_WATT + r'$', text)
    if not m:
        return [value]
    base = float(m.group(1))
    prefix = m.group(2) or ''
    watts = base * _SI.get(prefix, 1.0) if prefix else base
    aliases = [value, _plain(watts)]
    if watts >= 1000:
        aliases.extend(['%skW' % _plain(watts / 1000.0),
                        '%sk' % _plain(watts / 1000.0)])
    else:
        aliases.append('%sW' % _plain(watts))
        if watts < 1:
            aliases.append('%smW' % _plain(watts * 1000.0))
    return _dedupe(aliases)


def _generic_aliases(value):
    value = _clean(value)
    if not value:
        return []
    aliases = [value]
    if value.startswith('±'):
        aliases.append(value[1:].strip())
    for part in re.split(r'[;；,，/]', value):
        part = part.strip()
        if part and part != value:
            aliases.append(part)
    return _dedupe(aliases)


def normalize_value(name, value):
    """Return all searchable spellings for one parameter value."""
    value = _clean(value)
    if not value:
        return []
    name = _text(name)
    if '阻值' in name:
        return _resistance_aliases(value)
    if any(key in name for key in ('容值', '容量', '电容量')):
        return _capacitance_aliases(value)
    if '精度' in name:
        return _tolerance_aliases(value)
    if any(key in name for key in ('耐压', '额定电压', '工作电压')):
        return _voltage_aliases(value)
    if '功率' in name:
        return _power_aliases(value)
    # Unknown names (e.g. the single "规格" key used by quick-create) still
    # benefit from value-shape detection.
    aliases = _generic_aliases(value)
    if _looks_resistance(value):
        aliases.extend(_resistance_aliases(value))
    if _looks_capacitance(value):
        aliases.extend(_capacitance_aliases(value))
    if '%' in value or '±' in value:
        aliases.extend(_tolerance_aliases(value))
    if _looks_voltage(value):
        aliases.extend(_voltage_aliases(value))
    return _dedupe(aliases)


def build_search_params(parameters):
    """Build the normalized token string for selected key parameters."""
    tokens = []
    for name, value in key_pairs(parameters):
        raw = _raw(value)
        if raw:
            tokens.append(raw)
            normalized = unicodedata.normalize('NFKC', raw)
            if normalized != raw:
                tokens.append(normalized)
        tokens.extend(normalize_value(name, value))
    return ' '.join(_dedupe(tokens))


def search_tokens(query):
    """Split a free-text query into NFKC-normalized whitespace tokens."""
    text = _text(query)
    return _dedupe(text.split()) if text else []


def build_search_specs(raw):
    """Build the normalized token string from ``lab_specifications`` JSON."""
    if not raw:
        return ''
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return build_search_params([{'name': '规格', 'value': raw}])
    pairs = []
    if isinstance(data, dict):
        pairs = [{'name': key, 'value': value} for key, value in data.items()]
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                pairs.append({
                    'name': entry.get('name') or entry.get('key') or '',
                    'value': entry.get('value') or entry.get('val') or '',
                })
            else:
                pairs.append({'name': '规格', 'value': entry})
    else:
        pairs = [{'name': '规格', 'value': data}]
    return build_search_params(pairs)
