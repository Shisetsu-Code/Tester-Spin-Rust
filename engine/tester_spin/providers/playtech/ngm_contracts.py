"""Offline NGM declarations from captured client code and JMM, never replay."""
import ast
import base64
import hashlib
import json
import re
import warnings
from urllib.parse import urlsplit

from .client_sources import _function_bodies

NAME = r'[A-Za-z_$][\w$]*'
STRING = r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
MAX_BODY = 8*1024*1024


def _constants(source):
    constants = {}
    for match in re.finditer(r'(?<![\w$])('+NAME+r')=('+STRING+r')', source):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', SyntaxWarning)
                literal = ast.literal_eval(match[2])
            constants.setdefault(match[1], set()).add(literal)
        except (ValueError, SyntaxError):
            pass
    return constants


def _value_object_types(source):
    labels = {}
    for match in re.finditer(NAME+r"\([^;()]*['\"]([^'\"]+)['\"],(\d+),[^;()]*\)", source):
        labels.setdefault(match[1], set()).add(match[2])
    wire = set().union(*(labels.get(name, set()) for name in ('RequestMessage','AbstractGameRequest')))
    objects = labels.get('Object', set())
    if not wire or not objects:
        return set()
    parents = {}
    for m in re.finditer(NAME+r'\((\d+),(\d+),(?:\{[^{}]*\}|'+NAME+r')(?:,'+NAME+r')?\)', source):
        parents.setdefault(m[1], set()).add(m[2])
    values = set()
    for identity in parents:
        node, seen = identity, set()
        while node not in seen and len(seen)<64:
            if node in wire:
                break
            if node in objects:
                values.add(identity);break
            seen.add(node)
            if len(parents.get(node, set()))!=1:
                break
            node=next(iter(parents[node]))
    return values


def source_declarations(source):
    constants = _constants(source)
    concrete = {match[1] for match in re.finditer(
        NAME+r'\((\d+),\d+,(?:\{[^{}]*\}|'+NAME+r'),'+NAME+r'\)', source)}
    rows = []
    wire = set(_wire_declarations(source))
    value_types = _value_object_types(source)
    for match in re.finditer(NAME+r"\(("+NAME+r"),['\"]([^'\"]+)['\"],(\d+|null),[^;()]*\)", source):
        if (match[2], match[3]) not in wire and not (match[3] == 'null' and match[2].endswith('Request')):
            continue
        values = constants.get(match[1], set())
        rows.append(dict(name=match[2], namespace=next(iter(values)) if len(values) == 1 else None,
                         concrete=match[3] in concrete, value_object=match[3] in value_types))
    platform_namespaces = {row['namespace'] for row in rows
                           if row['name'] == 'PlatformRequest' and row['namespace']}
    for row in rows:
        row['channel'] = 'platform' if row['namespace'] and any(
            row['namespace'] == prefix or row['namespace'].startswith(prefix+'.')
            for prefix in platform_namespaces) else ('value_object' if row['value_object'] else 'wire_or_unbound')
    return rows



def _wire_declarations(source):
    """Names are descriptive; membership comes from the declared wire base."""
    declarations = list(re.finditer(NAME+r"\([^;()]*['\"]([^'\"]+)['\"],(\d+),[^;()]*\)", source))
    base = {m[2] for m in declarations if m[1] == 'AbstractGameRequest'}
    parents = {}
    for m in re.finditer(NAME+r'\((\d+),(\d+),(?:\{[^{}]*\}|'+NAME+r')(?:,'+NAME+r')?\)', source):
        parents.setdefault(m[1], set()).add(m[2])
    def wire(type_id):
        seen = set()
        while type_id not in seen and len(seen) < 64:
            if type_id in base:
                return True
            seen.add(type_id)
            choices = parents.get(type_id, set())
            if len(choices) != 1:
                return False
            type_id = next(iter(choices))
        return False
    return [(m[1], m[2]) for m in declarations if m[1].endswith('Request') or wire(m[2])]


def _message_id(body, functions, source):
    direct = re.findall(r'\.call\(this,('+NAME+r')\((\d+)\)\)', body)
    if len(direct) == 1:
        return int(direct[0][1]), 'literal'
    calls = re.findall(r'\.call\(this,('+NAME+r')\(('+NAME+r')\)\)', body)
    if len(calls) != 1:
        return None
    boxer, variable = calls[0]
    # A targeted lookup also handles large enum initializers omitted by the
    # bounded function reader. No expressions from captured code are evaluated.
    assignments = list(re.finditer(r'(?<![\w$.])'+re.escape(variable)+r'=(?![=])([^;{}]{1,256})', source))
    initializers = [name for name, (_, init_body) in functions.items()
                    if re.search(r'(?<![\w$.])'+re.escape(variable)+r'=', init_body)
                    and re.search(r'(?<![\w$])'+re.escape(name)+r'\(\);', body)]
    if len(initializers) != 1:
        return None
    expressions = [m[1] for m in assignments if m[1] != '0']
    if len(expressions) != 1:
        return None
    enum = re.fullmatch(r'\(('+NAME+r')\(\),('+NAME+r')\)\.('+NAME+r')\.('+NAME+r')', expressions[0])
    if not enum:
        return None
    writes = list(re.finditer(r'(?<![\w$.])'+re.escape(enum[2])+r'=(?![=])([^;{},]{1,256})', source))
    if len(writes) != 1:
        return None
    value = re.fullmatch(r'new ('+NAME+r')\('+re.escape(boxer)+r'\((\d+)\)\)', writes[0][1])
    if not value:
        return None
    args, wrapper = functions.get(value[1], ([], ''))
    if len(args) != 1 or wrapper != 'this.'+enum[3]+'='+args[0]:
        return None
    return int(value[2]), 'boxed_enum'


def request_catalog(source, *, value_classes=()):
    """Class + constructor + serializer bindings, with unbound fields explicit."""
    if len(source.encode('utf-8')) > MAX_BODY:
        return []
    functions = _function_bodies(source)
    constants = _constants(source)
    registrations = {}
    for match in re.finditer(NAME+r'\((\d+),\d+,(?:\{[^{}]*\}|'+NAME+r'),('+NAME+r')\)', source):
        registrations.setdefault(match[1], set()).add(match[2])
    declarations = {}
    for label, type_id in _wire_declarations(source):
        declarations.setdefault(label, set()).add(type_id)
    for match in re.finditer(NAME+r"\([^;()]*['\"]([^'\"]+)['\"],(\d+),[^;()]*\)", source):
        if match[1] in value_classes:
            declarations.setdefault(match[1], set()).add(match[2])
    rows = []
    for label, type_ids in declarations.items():
        if len(type_ids) != 1:
            continue
        type_id = next(iter(type_ids))
        constructors = registrations.get(type_id, set())
        if len(constructors) != 1:
            continue
        constructor = next(iter(constructors))
        body = functions.get(constructor, ([], ''))[1]
        message = _message_id(body, functions, source)
        if message is None:
            if label not in value_classes:
                continue
            message = (None, 'value-object')
        serializers = [(fn, args, body) for fn, (args, body) in functions.items()
                       if len(args) == 2 and re.search(NAME+r'\('+re.escape(args[0])+','+type_id+r'\)', body)]
        if len(serializers) != 1:
            continue
        serializer, args, body = serializers[0]
        aliases = re.findall(r'\b('+NAME+r')='+re.escape(args[0])+r';', body)
        if len(aliases) != 1:
            continue
        fields, declared, unresolved = {}, set(), set()
        recognized_output_uses = set()
        for call in re.finditer(NAME+r'\('+re.escape(args[1])+r',('+STRING+'|'+NAME+r'),', body):
            recognized_output_uses.add(body.index('('+args[1]+',', call.start())+1)
            token = call[1]
            if token.startswith(('"', "'")):
                semantic = ast.literal_eval(token)
            elif len(constants.get(token, set())) == 1:
                semantic = next(iter(constants[token]))
            else:
                unresolved.add(token)
                continue
            declared.add(semantic)
            prefix = body[:call.start()]
            assignment = re.search(r'('+NAME+r')=(?:'+NAME+r'\()?'+re.escape(aliases[0])+
                                   r'\.('+NAME+r')\)?;(?:\1!=null|!!\1)&&$', prefix)
            if assignment is None:
                array_arg = re.match(r'('+NAME+r')\)', body[call.end():])
                if array_arg:
                    assignment = re.search(r'('+NAME+r')='+re.escape(aliases[0])+r'\.('+NAME+
                        r');if\(\1!=null\)\{('+NAME+r')=\1;'+re.escape(array_arg[1])+r'=new '+NAME+
                        r'(?:\(\))?;[^{}]{0,128}for\('+NAME+r'=\3\.'+NAME+r'\(\);[^{}]{0,128}\)\{([^{}]{0,256})\}$', prefix)
                    if assignment and not re.search(NAME+r'\('+re.escape(array_arg[1])+',', assignment[4]):
                        assignment = None
            if assignment:
                previous = fields.get(semantic)
                if previous is not None and previous != assignment[2]:
                    unresolved.add(semantic)
                else:
                    fields[semantic] = assignment[2]
        masked = re.sub(STRING, lambda match: ' '*len(match[0]), body)
        output_uses = {match.start() for match in re.finditer(
            r'(?<![\w$.])'+re.escape(args[1])+r'(?![\w$])', masked)}
        if output_uses-recognized_output_uses:
            unresolved.add('OUTPUT_USE_UNBOUND')
        for key in unresolved:
            fields.pop(key, None)
        rows.append(dict(name=label, message_id=message[0], id_evidence=message[1], class_id=int(type_id),
            constructor=constructor, serializer=serializer, fields=fields, wire_message=not label.endswith('Request'),
            declared_fields=sorted(declared), unresolved_fields=sorted((declared-set(fields)) | unresolved)))
    counts = {}
    for row in rows:
        counts[row['constructor']] = counts.get(row['constructor'], 0)+1
    return sorted((row for row in rows if counts[row['constructor']] == 1),
                  key=lambda row: (row['message_id'] is None, row['message_id'] or 0, row['name']))


def functional_manifest(document, code):
    config = document.get('config') if isinstance(document, dict) else None
    if not isinstance(config, dict) or config.get('game_code') != code:
        raise ValueError('NGM_MANIFEST_IDENTITY_MISMATCH')
    controls, math_resources, unresolved_templates = [], [], []
    config = dict(config)
    # Mathematical tables remain in the original HAR. Keep betting/menu
    # declarations inline; these references remove neither fields nor provenance.
    for key in ('reels', 'wild_state_to_reel_weights', 'fs_sequences_weights', 'paytable'):
        if key in config:
            encoded = json.dumps(config[key], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(encoded) > 4096:
                ref = '/config/'+key
                math_resources.append(dict(source_ref=ref, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest()))
                config[key] = dict(source_ref=ref)
    visual = {'pos', 'size', 'format', 'background', 'slice', 'slices', 'animations', 'animation', 'content'}

    def resolve(value, path, chain=()):
        reference = value.get('@P')
        if reference is None:
            return value, []
        target = reference.get('#ID') if isinstance(reference, dict) else None
        if not isinstance(target, str) or len(chain) >= 32:
            unresolved_templates.append(dict(ref=path, reason='INVALID_OR_TOO_DEEP'))
            return value, []
        target = '/'+target.lstrip('/')
        if target in chain:
            unresolved_templates.append(dict(ref=path, template_ref=target, reason='CYCLE'))
            return value, []
        template = document
        for part in target.strip('/').split('/'):
            template = template.get(part) if isinstance(template, dict) else None
        if not isinstance(template, dict):
            unresolved_templates.append(dict(ref=path, template_ref=target, reason='MISSING'))
            return value, []
        inherited, refs = resolve(template, path, chain+(target,))
        return dict(inherited, **value), [target]+refs

    def walk(value, path):
        if isinstance(value, dict):
            effective, refs = resolve(value, path)
            kind = effective.get('type', '')
            if isinstance(kind, str) and ('button' in kind or any(k in effective for k in ('action', 'command', 'choices', 'options'))):
                controls.append(dict(ref=path, template_refs=refs, **{k: v for k, v in effective.items() if k not in visual and k not in ('ref', 'template_refs')}))
            for key, child in value.items():
                walk(child, path+'/'+str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path+'/'+str(index))

    for root in ('ui', 'scenes'):
        walk(document.get(root, {}), '/'+root)
    return dict(game_code=code, configuration=config, controls=controls, math_resources=math_resources,
                inventory_state='UNKNOWN', unresolved_templates=unresolved_templates, control_presence_is_not_purchase_evidence=True)


def passive_request_roles(catalog, *, structured=None):
    """Observe reviewed non-entry messages, never execute them or infer prices."""
    metadata = {'windowId', 'ID', 'umid'}
    contracts = {'LogUserPreferencesRequest': ('aux', metadata | {'value'}),
                 'StartBonusGameRequest': ('continuation', metadata)}
    roles = {}
    for row in catalog:
        spec = contracts.get(row['name'])
        if row.get('unresolved_fields'):
            continue
        declared = set(row.get('declared_fields', []))
        if not spec and row.get('wire_message') and declared == metadata and declared == set(row.get('fields', {})):
            roles[row['name']] = 'unhandled_candidate'
            continue
        if not spec:
            continue
        if declared and declared <= spec[1] and declared == set(row.get('fields', {})):
            roles[row['name']] = spec[0]
    if structured:
        roles.update(structured.get('lifecycle_roles', {}))
    return roles


def _body(entry):
    content = entry.get('response', {}).get('content', {})
    text = content.get('text')
    if not isinstance(text, str) or len(text) > MAX_BODY*2:
        raise ValueError('NGM_BODY_MISSING_OR_TOO_LARGE')
    if content.get('encoding') == 'base64':
        raw = base64.b64decode(text, validate=True)
        if len(raw) > MAX_BODY:
            raise ValueError('NGM_BODY_TOO_LARGE')
        text = raw.decode('utf-8')
    elif content.get('encoding') not in (None, ''):
        raise ValueError('NGM_BODY_ENCODING_UNSUPPORTED')
    if len(text.encode('utf-8')) > MAX_BODY:
        raise ValueError('NGM_BODY_TOO_LARGE')
    declared_size = content.get('size')
    if type(declared_size) is int and declared_size > len(text.encode('utf-8')):
        raise ValueError('NGM_BODY_TRUNCATED')
    return text


def analyze_har(har, code):
    """Report only; imports no captured sessions and makes no network calls."""
    from .ngm_capture import capture_diagnostics
    capture = capture_diagnostics(har)
    sources, manifests, unresolved = [], [], []
    for index, entry in enumerate(har.get('log', {}).get('entries', [])):
        parsed = urlsplit(entry.get('request', {}).get('url', ''))
        if parsed.scheme != 'https' or parsed.hostname != 'cachedownload.playtechone.com':
            continue
        if '/ngmdistributed/' not in parsed.path or '/'+code+'/' not in parsed.path:
            continue
        if entry.get('response', {}).get('status') != 200:
            continue
        ref = 'http:'+str(index)
        try:
            if parsed.path.endswith('.cache.js'):
                source = _body(entry)
                catalog = request_catalog(source)
                if catalog:
                    declarations = source_declarations(source)
                    sources.append((ref, source, catalog, declarations))
                    names = {row['name'] for row in declarations if row['concrete'] and row['channel'] not in ('platform','value_object')}
                    unresolved.extend('NGM_REQUEST_CONTRACT_UNBOUND:'+name
                                      for name in sorted(names-{row['name'] for row in catalog}))
            elif parsed.path.endswith('.jmm'):
                document = json.loads(_body(entry))
                if isinstance(document, dict) and isinstance(document.get('config'), dict):
                    manifests.append((ref, functional_manifest(document, code)))
        except (ValueError, UnicodeError, TypeError) as exc:
            unresolved.append(ref+':'+str(exc))
    report = dict(schema='tester-spin/ngm-static-contracts/v1', game_code=code,
                  network_used=False, scripts_executed=False, certifies_game_ok=False,
                  request_count=0, unresolved=unresolved, capture_diagnostics=capture)
    if len(sources) == 1:
        ref, source, catalog, declarations = sources[0]
        report.update(source_ref=ref, source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
                      requests=catalog, request_count=len(catalog), source_declarations=declarations)
    else:
        unresolved.append('NGM_CLIENT_SOURCE_MISSING' if not sources else 'NGM_CLIENT_SOURCE_AMBIGUOUS')
    if len(manifests) == 1:
        report.update(manifest_ref=manifests[0][0], manifest=manifests[0][1])
    else:
        unresolved.append('NGM_MANIFEST_MISSING' if not manifests else 'NGM_MANIFEST_AMBIGUOUS')
    if not sources:
        capture['next_steps'].append('Falta el cliente JavaScript .cache.js del juego. Recargá con caché desactivada y exportá el HAR con cuerpos de respuesta, incluyendo JavaScript y el manifiesto .jmm de la misma versión.')
    if not manifests:
        capture['next_steps'].append('Falta el manifiesto del juego: incluí la respuesta .jmm con config, sin filtros que eliminen recursos.')
    from .ngm_plan import build_execution_plan
    report['execution_plan'] = build_execution_plan(report, sources[0][1] if len(sources) == 1 else '')
    return report


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Extract NGM declarations offline; never sends wagers.')
    parser.add_argument('har', type=Path)
    parser.add_argument('--code', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.suffix.lower() != '.json' or args.out.resolve() == args.har.resolve() or (
            args.out.exists() and args.har.samefile(args.out)):
        parser.error('Output must be a separate JSON report; the source HAR is never replaced')
    if args.har.stat().st_size > 256*1024*1024:
        parser.error('HAR exceeds 256 MiB')
    report = analyze_har(json.loads(args.har.read_text(encoding='utf-8-sig')), args.code)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(args.out.resolve()), request_count=report['request_count'], unresolved=report['unresolved'], capture_diagnostics=report['capture_diagnostics'])))


if __name__ == '__main__':
    main()
