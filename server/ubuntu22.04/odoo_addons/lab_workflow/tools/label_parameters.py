"""Choose label-sized specifications; the complete record remains unchanged."""


def key_parameters(parameters):
    pairs = list(parameters or [])
    if any('阻值' in str(p.get('name', '')) for p in pairs):
        keys = ('阻值', '精度', '功率')
    elif any(any(k in str(p.get('name', '')) for k in ('容值', '容量', '电容量')) for p in pairs):
        keys = ('容值', '容量', '电容量', '耐压', '额定电压', '介质', '材质')
    else:
        return pairs[:3]
    return [p for p in pairs if any(k in str(p.get('name', '')) for k in keys)][:4]
