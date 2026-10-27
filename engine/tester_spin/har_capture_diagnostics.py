"""Structural HAR checks shared by offline analysis and manual capture import."""


def capture_entries(document):
    if not isinstance(document, dict) or not isinstance(document.get('log'), dict):
        raise ValueError('HAR_INVALID_STRUCTURE: se esperaba log.entries; exportá nuevamente el HAR completo.')
    entries = document['log'].get('entries')
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError('HAR_INVALID_STRUCTURE: log.entries debe ser una lista de peticiones.')
    for entry in entries:
        for key in ('request', 'response'):
            if key in entry and not isinstance(entry[key], dict):
                raise ValueError('HAR_INVALID_STRUCTURE: petición o respuesta inválida.')
        request, response = entry.get('request', {}), entry.get('response', {})
        if not isinstance(request.get('url', ''), str) or not isinstance(response.get('content', {}), dict):
            raise ValueError('HAR_INVALID_STRUCTURE: URL o contenido inválido.')
    return entries
