"""A client displayed remaining counter is independent of server aggregate totals."""
import hashlib
import math
import re
from functools import lru_cache
from .protocol import MAX_BODY


def counter_contract(source):
    """Return an independent snapshot of the exact client counter binding."""
    if not isinstance(source,str) or len(source)>MAX_BODY:return None
    proof=_counter_binding(source)
    if proof is None:return None
    return {'field':proof[0],'source_sha256':proof[1]}


@lru_cache(maxsize=2)
def _counter_binding(source):
    """Require the same game owner to supply the keypad's direct model counter."""
    if not isinstance(source,str) or len(source)>MAX_BODY:return None
    # Inspect only bounded windows around actual keypad consumers. Matching an
    # unbounded owner against an embedded asset string can become quadratic.
    fields=set()
    for consumer in re.finditer(r'\.setZeroBetSpinCounter\(',source):
        start=max(0,consumer.start()-160);window=source[start:consumer.start()+240]
        pattern=(r'([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*){0,5})\.keypadPlugin\.setZeroBetSpinCounter\('
            r'\1\.model\.(data\.)?([A-Za-z_$][\w$]*)\)')
        for match in re.finditer(pattern,window):
            if match[2]:fields.add(match[3])
            else:
                field=_flat_field(source,start+match.start(),match[1],match[3])
                if field is None:return None
                fields.add(field)
    if len(fields)!=1:return None
    return next(iter(fields)),hashlib.sha256(source.encode('utf-8')).hexdigest()


def _flat_field(source,position,owner,property_name):
    """Follow the imported game owner to its actual model's onGame parser."""
    from .client_actions import _block
    from .static_bindings import class_record,_module_headers
    from .lifecycle import expressions
    if owner.count('.')>1:return None
    game=class_record(source,position,owner,_block)
    if not game:return None
    header=source[max(0,game[2]-180):game[2]]
    local=re.search(r'class ([\w$]+)(?: extends [\w$.]+)?$',header)
    if not local:return None
    assignments=list(re.finditer(re.escape(local[1])+r'\.model=new ([\w$]+\.[\w$]+)\(',game[0]))
    if len(assignments)!=1:return None
    headers=[m for m in _module_headers(source) if m.end()<=game[2]]
    if not headers:return None
    module=_block(source,headers[-1].end()-1,len(source))
    if not module:return None
    aliases={local[1]}
    for _ in range(8):
        discovered=set()
        for alias in aliases:
            discovered.update(re.findall(r'(?<![\w$.])([\w$]+(?:\.[\w$]+){0,3})='+re.escape(alias)+r'(?=[,;)}\]])',module))
        if discovered<=aliases:break
        aliases.update(discovered)
    else:return None
    model_property=r'(?:\.model|\[\s*["\']model["\']\s*\])'
    model_writes=[]
    for alias in aliases:
        model_writes.extend(re.finditer(r'(?<![\w$.])'+re.escape(alias)+model_property+r'(?:[+*/-]?=(?![=>])|\+\+|--)',module))
    if len(model_writes)!=1:return None
    assignment=assignments[0]
    model=class_record(source,game[2]+assignment.start(),assignment[1],_block)
    if not model:return None
    cursor=1;parsers=[];getters=[]
    while cursor<len(model[0])-1:
        member=re.match(r'(?:(get|set|static) )?([\w$]+)\(([^)]*)\)\{',model[0][cursor:])
        if not member:return None
        body=_block(model[0],cursor+member.end()-1,len(model[0]))
        if not body:return None
        if member[2]==property_name:
            if member[1]!='get' or member[3]:return None
            getters.append(body[1:-1])
        if member[2]=='onGame' and member[1] is None:parsers.append((member[3],body[1:-1]))
        cursor+=member.end()-1+len(body)
    if getters:
        if len(getters)!=1:return None
        return _getter_field(source,model,property_name,getters[0],_block)
    if len(parsers)!=1:return None
    arguments,body=parsers[0]
    parameters=re.fullmatch(r'([\w$]+)(?:,[\w$]+=(?:!0|!1))?',arguments)
    if not parameters:return None
    argument=parameters[1]
    parts=expressions(body)
    while parts and re.fullmatch(r'(?:var|let) [\w$]+',parts[0]):parts.pop(0)
    if not parts or parts[0]!='super.onGame('+argument+')':return None
    pattern=r'this\.'+re.escape(property_name)+r'='+re.escape(argument)+r'\.([\w$]+)'
    values=[m[1] for part in parts if (m:=re.fullmatch(pattern,part))]
    if len(values)!=1:return None
    effect='this.'+property_name+'='+argument+'.'+values[0]
    if any(re.match(r'^(?:if|return|throw|for|while|switch|try|do)\b',part) for part in parts[:parts.index(effect)]):return None
    consumed_property=r'(?:\.'+re.escape(property_name)+r'|\[\s*["\']'+re.escape(property_name)+r'["\']\s*\])'
    mutation=r'this'+consumed_property+r'(?:[+*/-]?=(?![=>])|\+\+|--)'
    if len(re.findall(mutation,body))!=1:return None
    if re.search(r'(?:delete\s+|(?:\+\+|--)\s*)this'+consumed_property,body):return None
    if re.search(r'\bthis\[[^\]]{1,100}\](?:[+*/-]?=(?![=>])|\+\+|--)',body):return None
    if re.search(r'(?<![\w$.])'+re.escape(argument)+r'=(?![=>])',body):return None
    raw_property=r'(?:\.'+re.escape(values[0])+r'|\[\s*["\']'+re.escape(values[0])+r'["\']\s*\])'
    if re.search(re.escape(argument)+raw_property+r'(?:[+*/-]?=(?![=>])|\+\+|--)',body):return None
    if re.search(r'(?:delete\s+|(?:\+\+|--)\s*)'+re.escape(argument)+raw_property,body):return None
    if re.search(r'(?<![\w$.])'+re.escape(argument)+r'\[[^\]]{1,100}\](?:[+*/-]?=(?![=>])|\+\+|--)',body):return None
    return values[0]


def _getter_field(source,model,property_name,body,block):
    """Read an exact raw-field getter; the response must still contain that field."""
    from .async_lifecycle import _owner,_aliases,_writes
    direct=re.fullmatch(r'return this\.data\.([\w$]+)',body)
    nullish=re.fullmatch(r'var ([\w$]+);return null!==\(\1=this\.data\.([\w$]+)\)&&void 0!==\1\?\1:0',body)
    if direct:field=direct[1]
    elif nullish:field=nullish[2]
    else:return None
    # Ordinary construction or a late prototype override cannot replace the
    # getter that supplied the displayed counter.
    if _writes(model[0],{'this'},property_name):return None
    if re.search(r'this\[[^\]]+\]\s*=(?!=)',model[0]):return None
    owner=_owner(source,model[2],block)
    if not owner:return None
    _,module,_=owner
    prefix=source[max(0,model[2]-200):model[2]]
    named=re.search(r'class ([\w$]+)(?: extends [\w$.]+)?$',prefix)
    anonymous=re.search(r'([\w$]+\.[\w$]+)=class(?: extends [\w$.]+)?$',prefix)
    if named:
        seeds={named[1]}
        seeds.update(m[1] for m in re.finditer(r'([\w$]+\.[\w$]+)='+re.escape(named[1])+r'(?=[,;}])',module))
    elif anonymous:seeds={anonymous[1]}
    else:return None
    aliases=_aliases(module,seeds)
    if aliases is None or _writes(module,aliases,'prototype'):return None
    prototypes=_aliases(module,{alias+'.prototype' for alias in aliases})
    if prototypes is None or _writes(module,prototypes,property_name):return None
    targets='(?:'+'|'.join(re.escape(value) for value in aliases|prototypes)+')'
    if re.search(r'Object\.(?:assign|defineProperty|defineProperties|setPrototypeOf)\('+targets+r'(?=[,)])',module):return None
    raw=r'this\.data(?:\.'+re.escape(field)+r'|\[["\']'+re.escape(field)+r'["\']\])'
    if re.search(raw+r'\s*(?:[+*/-]?=(?![=>])|\+\+|--)',model[0]):return None
    return field


def regular_counter(answer,source):
    """Select only the bound game counter; outer totals may include special spins."""
    contract=counter_contract(source)
    if contract is None:raise ValueError('Nolimit City: contador restante sin declaración cliente')
    return counter_from_contract(answer,contract)


def counter_from_contract(answer,contract):
    if (not isinstance(contract,dict) or not isinstance(contract.get('field'),str)
            or not re.fullmatch(r'[\w$]+',contract['field'])
            or not isinstance(contract.get('source_sha256'),str)
            or not re.fullmatch(r'[0-9a-f]{64}',contract['source_sha256'])):
        raise ValueError('Nolimit City: prueba de contador cliente inválida')
    game=answer.get('game') or {};field=contract['field'];value=game.get(field)
    if type(value) is float and math.isfinite(value) and value.is_integer() and 0<=value<=2**53-1:
        value=int(value)
    if type(value) is not int or value<0:raise ValueError('Nolimit City: contador restante cliente inválido')
    if field!='freespinsLeft' and 'freespinsLeft' in game and (type(game['freespinsLeft']) is not int or game['freespinsLeft']!=value):
        raise ValueError('Nolimit City: alias del contador cliente contradictorio')
    if 'remainingFreeSpins' in answer and (type(answer['remainingFreeSpins']) is not int or answer['remainingFreeSpins']<0):
        raise ValueError('Nolimit City: total de giros servidor inválido')
    return value
