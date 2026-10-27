"""Conservative certificates for the generated RubyPlay select contract."""
from __future__ import annotations
import re
from typing import Any

ID = r'[A-Za-z_$][A-Za-z0-9_$]*'
SHUFFLE = 'shuffle$com_gongxigames_math_core_game_random_Random$int_A'


def certify_select_domain(source: str, evidence: dict[str, Any], action_map: dict[int, str]) -> dict[str, str]:
    if not evidence.get('active_engine_constructor'):
        return {}
    engine = str(evidence['active_engine'])
    excerpt = str(evidence['source_excerpt'])
    construction = re.search(rf'new\s+({ID})\(({ID})\.{re.escape(SHUFFLE)}\(', excerpt)
    if not construction:
        return {}
    bonus_alias, shuffle_alias = construction.groups()
    array_name = re.match(rf"let\s+({ID})=", excerpt).group(1)
    if len(re.findall(rf"(?<![A-Za-z0-9_$]){re.escape(array_name)}(?![A-Za-z0-9_$])", excerpt)) != 2:
        return {}
    # All constructors of this exported bonus must be accounted for. Additional
    # construction sites need their own analysis, even if their arrays coincide.
    if len(re.findall(rf'\bnew\s+{re.escape(bonus_alias)}\(', source)) != 1:
        return {}
    alias_match = re.search(rf'\}},?{re.escape(bonus_alias)}=({ID});', source)
    if not alias_match:
        return {}
    original = alias_match.group(1)
    bonus_start = source.rfind(f'var {original}=class', 0, alias_match.start())
    if bonus_start < 0:
        return {}
    bonus = source[bonus_start:alias_match.start()+1]
    if re.search(rf'\b{re.escape(bonus_alias)}\.generate\(|\b{re.escape(original)}\.generate\(', source):
        return {}
    # The supported generated class stores the constructor array, swaps entries
    # in pick(), and restores exactly what writeIntArray serialized in read().
    pick = re.search(r'pick\((\w+)\)\{this.index=\1;for\(let (\w+)=0;\2<this.values.length;\2\+\+\)this.values\[\2\]===this.pickValue&&\2!==\1&&\(this.values\[\2\]=this.values\[\1\],this.values\[\1\]=this.pickValue\);return this.pickValue\}', bonus)
    if not pick or 'getValues(){return this.values}' not in bonus:
        return {}
    stripped = bonus.replace(pick.group(0), '')
    writes = re.findall(r'this.values\s*=\s*([^,;}]+)', stripped)
    if len(writes) != 6 or writes.count('null') != 4 or len([v for v in writes if re.fullmatch(ID,v)]) != 5:
        return {}
    if not re.search(r'this.values=\w+,this.pickValue=\w+', bonus):
        return {}
    if re.search(r'this.values(?:\[|\.(?:push|pop|splice|shift|unshift|length\s*=))', stripped):
        return {}
    shuffle = re.search(
        rf'static {re.escape(SHUFFLE)}\((?P<rng>{ID}),(?P<arr>{ID})\)\{{let (?P<n>{ID})=(?P=arr).length;(?P=arr)=(?P=arr).slice\(0,(?P=n)\);for\(let (?P<idx>{ID})=0;(?P=idx)<(?P=n)-1;(?P=idx)\+\+\)\{{let (?P<other>{ID})=(?P=idx)\+(?P=rng).nextInt\$int\((?P=n)-(?P=idx)\),(?P<temp>{ID})=(?P=arr)\[(?P=other)\];(?P=arr)\[(?P=other)\]=(?P=arr)\[(?P=idx)\],(?P=arr)\[(?P=idx)\]=(?P=temp)\}}return (?P=arr)\}}',source)
    if not shuffle:
        return {}
    # Bind the exact shuffle body to the utility used by this constructor.
    utility_start = source.rfind(f'{shuffle_alias}=class{{', 0, shuffle.start())
    if utility_start < 0 or source.find('};', utility_start) < shuffle.end():
        return {}
    handler_tag = re.search(rf'({ID})\.__class="com\.gongxigames\.math\.core\.game\.message\.handlers\.SelectMessageHandler"',source)
    if not handler_tag:
        return {}
    base = handler_tag.group(1)
    base_start = source.rfind(f'var {base}=class',0,handler_tag.start())
    handler = source[base_start:handler_tag.start()]
    bounded = re.search(rf'handle\((?P<msg>{ID}),(?P<session>{ID})\)\{{let (?P<bonus>{ID})=(?P=session).getBonus\({ID}\.SELECT_BONUS\),(?P<index>{ID})={re.escape(base)}.checkIndex\((?P=msg),(?P=bonus).getValues\(\).length\),(?P<value>{ID})=(?P=bonus).pick\((?P=index)\);return this.postSelect\((?P=value),(?P=session)\),(?P=msg).createResponse\(\).addField\({ID}\.VALUE,(?P=value)\)\}}',handler)
    guard = re.search(r'static checkIndex\((\w+),(\w+)\)\{let (\w+)=\1.getField\(\w+.INDEX\);if\(\3==null\|\|\3<0\|\|\3>=\2\)throw new \w+\(\w+.INTERNAL_SERVER_ERROR\);return \3\}',handler)
    if not bounded or not guard:
        return {}
    select_ids=[number for number,name in action_map.items() if name=='select']
    if len(select_ids)!=1:
        return {}
    engine_start = source.rfind(f"var {engine}=class", 0, int(evidence["source_offset"]))
    engine_end = source.find(f"{engine}.__class=", engine_start)
    registration = re.search(rf'this.handlers,{select_ids[0]},new {re.escape(engine)}\.({ID})\(this,this\)',source[engine_start:engine_end])
    if not registration:
        return {}
    member = registration.group(1)
    child = re.search(rf'class ({ID}) extends {re.escape(base)}\{{(.*?)\}}({ID})\.{re.escape(member)}=\1,',source,re.S)
    if not child or re.search(r'\bhandle(?:\$[^({{]*)?\(',child.group(2)) or 'SELECT_BONUS' in child.group(2) or '.values' in child.group(2):
        return {}
    # The generated inner handler assignment must be in the engine's IIFE.
    closure = source.find(f'}})({engine}||={{}})', child.end())
    if closure < 0 or closure-child.end()>1000:
        return {}
    return {'constructor':excerpt,'handler_registration':registration.group(0),
            'handler_subclass':child.group(0),'handler_bound':bounded.group(0)+guard.group(0),
            'bonus_pick':pick.group(0),'shuffle':shuffle.group(0)}
