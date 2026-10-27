"""Read declared GPAS JMM adapter maps without executing client code."""
import re
from copy import deepcopy
from urllib.parse import unquote


def projects(sources):
    # Primary game project is passed to the game constructor. Conditional .push
    # projects are UI extensions and cannot be merged as unconditional authority.
    return sorted(set(path for source in sources for path in re.findall(r"super\([^;()]{1,128},[\"'](jmm/[A-Za-z0-9_./%-]+\.jmp)[\"']\)",source) if '..' not in unquote(path).split('/') and chr(92) not in unquote(path)))



def config_paths(project):
    modules=project.get('modules',{})
    if not isinstance(modules,dict):raise ValueError('CLIENT_PROJECT_MODULES_UNKNOWN')
    module=modules.get('unknown',modules.get('desktop'))
    if not isinstance(module,dict):raise ValueError('CLIENT_DESKTOP_MODULE_UNKNOWN')
    paths=module.get('jmms')
    if not isinstance(paths,list) or len(paths)>128:raise ValueError('CLIENT_PROJECT_CONFIG_LIMIT')
    if any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_./%-]+\.jmm',p) or unquote(p).startswith('/') or '..' in unquote(p).split('/') or chr(92) in unquote(p) for p in paths):raise ValueError('CLIENT_PROJECT_PATH_UNBOUND')
    return list(dict.fromkeys(paths))


def merge_maps(documents):
    result={}
    for document in documents:
        config=document.get('config',{}) if isinstance(document,dict) else {}
        adapter=config.get('game_adapter',{}) if isinstance(config,dict) else {}
        if not isinstance(adapter,dict):raise ValueError('CLIENT_ADAPTER_INVALID')
        for key in ('bet_features','bet_feature_types'):
            if key not in adapter:continue
            value=adapter[key]
            if not isinstance(value,dict) or len(value)>256 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>128 or len(v)>256 for k,v in value.items()):raise ValueError('CLIENT_ADAPTER_MAP_INVALID')
            result.setdefault(key,{}).update(deepcopy(value))
    return result


def mapped_kind(name,maps):
    features=maps.get('bet_features',{});types=maps.get('bet_feature_types',{})
    aliases=[alias for alias,value in features.items() if value==name]
    if len(aliases)!=1:return None
    # This restricted grammar has no repetition or nested expressions.
    kinds=set()
    for kind,pattern in types.items():
        if not re.fullmatch(r'[A-Za-z0-9_\-^$]+(?:\[[A-Za-z0-9_|]+\])?',pattern):continue
        if re.search(pattern,aliases[0]):kinds.add(kind)
    if len(kinds)!=1:return None
    return {'regular':'SPIN','buy_feature':'PURCHASE','lucky_box':'PURCHASE','extra_bet':'ANTE_BET'}.get(next(iter(kinds)))
