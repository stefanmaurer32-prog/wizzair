def get_header_value(label):
    for i, line in enumerate(header):
        if label.lower() in line.lower():
            value = line.split(':', 1)[-1].strip()
            if value and value.lower() not in ('last run:', 'departure period:'):
                return value
    return 'Keine Angabe'

cache.update(
    at=time.time(),
    routes=sorted(routes),
    period=get_header_value('Departure period:'),
    updated=get_header_value('Last run:')
)
