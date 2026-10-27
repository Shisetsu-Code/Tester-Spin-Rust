"""Read monetary field declarations from the exact client without executing JS."""
import re
from functools import lru_cache
from .client_actions import _block
from .lifecycle import methods,expressions
from .protocol import MAX_BODY


def _object_properties(value):
    if not value.startswith('{') or _block(value,0)!=value:return []
    return expressions(value[1:-1])


def monetary_fields(source):
    """Resolve one unambiguous exported parser and its direct spin getter."""
    if not isinstance(source,str) or len(source)>MAX_BODY:return None
    fields=_monetary_fields(source)
    return dict(fields) if fields else None


@lru_cache(maxsize=2)
def _monetary_fields(source):
    candidates=[]
    for export in re.finditer(r'\b\w+\.\w+=class\{',source):
        body=_block(source,export.end()-1)
        if not body or 'getParsedData:' not in body:continue
        available=methods(body,_block)
        options=available.get('getActionSpinOptions')
        if not options or not options[1].startswith('return{'):continue
        properties=_object_properties(options[1][len('return'):])
        parsers=[value for value in properties if value.startswith('getParsedData:')]
        if len(parsers)!=1:continue
        parser=re.fullmatch(r'getParsedData:\((\w+),(\w+),(\w+)\)=>\((.*)\)',parsers[0],re.S)
        if not parser:continue
        args=parser.groups()[:3];data=re.escape(args[0])
        if len(set(args))!=len(args):continue
        returned=expressions(parser[4])
        if not returned:continue
        # The observed comma prefix only stores a UI flag on this object.
        # Unknown calls or writes to response arguments are not transparent.
        prefix=(data+r'\.\w+===\w+\.\w+\.[A-Z][A-Z0-9_]*&&\(this\.\w+='+data+r'\.\w+\)')
        if any(not re.fullmatch(prefix,value) for value in returned[:-1]):continue
        # The final comma expression must return the literal monetary object.
        # Nested history functions and string properties are never observations.
        output=_object_properties(returned[-1])
        if any(not re.match(r'[A-Za-z_$][A-Za-z0-9_$]*:',value) for value in output):continue
        if any(sum(value.startswith(key+':') for value in output)!=1 for key in ('totalWin','totalSpinWinnings')):continue
        totals=[match[1] for value in output if (match:=re.fullmatch(r'totalWin:'+data+r'\.(\w+)',value))]
        getters=[match.groups() for value in output if (match:=re.fullmatch(r'totalSpinWinnings:this\.(\w+)\((\w+(?:,\w+)*)\)',value))]
        if len(totals)!=1 or len(getters)!=1:continue
        name,actual_text=getters[0];actual=actual_text.split(',')
        # The response must remain the first actual argument. Other arguments
        # may be omitted, but never reordered, duplicated or supplied globally.
        if (actual[0]!=args[0] or len(set(actual))!=len(actual)
                or any(value not in args for value in actual)
                or [args.index(value) for value in actual]!=sorted(args.index(value) for value in actual)):continue
        getter=available.get(name)
        if not getter or not re.fullmatch(r'\w+(?:,\w+)*',getter[0]):continue
        formal=getter[0].split(',')
        if len(formal)!=len(actual) or len(set(formal))!=len(formal):continue
        member=r'(?:\.'+re.escape(name)+r'|\[\s*[\"\']'+re.escape(name)+r'[\"\']\s*\])'
        if re.search(r'this'+member+r'\s*(?:[+*/-]?=(?!=)|\+\+|--)',body):continue
        if any(re.search(r'\b'+re.escape(arg)+r'\s*=(?!=)',value) for arg in args for value in returned[:-1]):continue
        value=re.fullmatch(r'return '+re.escape(formal[0])+r'\.(\w+)',getter[1])
        if value and not any('balance' in field.lower() for field in (value[1],totals[0])):
            candidates.append({'spin':value[1],'round':totals[0]})
    return candidates[0] if len(candidates)==1 else None
