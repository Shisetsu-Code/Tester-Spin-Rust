"""KA public-client capability contract. Unknown client shapes stay unresolved."""
import re

SOURCE='startGame.dbf + game descriptor + RMP buy controller'


def _methods(source, marker="xd.extend({", reject_slashes=True, include_end=False):
    """Only methods on the outer descriptor, excluding nested objects/strings."""
    start=source.find(marker)
    if start<0:return {}
    start=source.find('{',start)
    depth=0;quote=None;escape=False;levels={};end=None
    for i in range(start,len(source)):
        char=source[i];levels[i]=-1 if quote else depth
        if quote:
            if escape:escape=False
            elif char=='\\':escape=True
            elif char==quote:quote=None
        elif char in ('"', "'"):quote=char
        elif char=='`' or reject_slashes and char=='/':return {}
        elif char=='{':depth+=1
        elif char=='}':
            depth-=1
            if depth==0:end=i+1;break
    if end is None:return {}
    methods={}
    for match in re.finditer(r'(?:"([^"\\]+)"|([\w$]+))\s*:\s*',source[start:end]):
        position=start+match.start()
        if levels.get(position)!=1:continue
        name=match[1] or match[2]
        function=re.match(r'function\([^)]*\)\{',source[start+match.end():end])
        if not function:
            methods[name]='UNRECOGNIZED_MEMBER'
            continue
        opening=start+match.end()+function.end()-1
        closing=next((i for i in range(opening+1,end) if source[i]=='}' and levels.get(i)==2),None)
        if closing is None:return {}
        methods[name]=re.sub(r'\s+','',source[opening+1:closing])
    return (methods,end) if include_end else methods


def _top_level_prefix(prefix):
    remaining=prefix.strip()
    remaining=re.sub(r'^([\"\'])use strict\1\s*;','',remaining).strip()
    while remaining:
        match=re.match(r'(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*xd\.extend\(\{',remaining)
        if not match or match[1] in {'xd','Uc','Eba','v','ce','A','Ab','wc'}:return False
        parsed=_methods(remaining,include_end=True)
        if not isinstance(parsed,tuple):return False
        closing=re.match(r'\)\s*;',remaining[parsed[1]:])
        if not closing:return False
        remaining=remaining[parsed[1]+closing.end():].strip()
    return True


def client_declarations(common, client, symbol, initial):
    unknown={'complete':False,'source':SOURCE,'options':[], 'reason':'CLIENT_CAPABILITY_UNRESOLVED'}
    result={'domains':{'purchase':dict(unknown),'ante':dict(unknown)},'modes':[]}
    # This is a recognized provider implementation, not a symbol whitelist.
    compact=re.sub(r'\s+','',common)
    required=['oda:function(){return!1}', 't$a:function(){return!1}',
              'this.cee()?Ab.kW(this.la,[1],', 'a.pos=[];',
              'a.YSb(b)', 'Uc=Eba.extend(', 'Oia:function(){returnthis.oda()?newEba:null}', 'v.uoa=a.EQd', 'b=a.dbf', 'a.Xqa(this.Ol,this.mj,this.ko,this.ti)']
    if not all(token in compact for token in required):
        from .declaration_names import normalize_declaration_sources
        common,client=normalize_declaration_sources(common,client)
        compact=re.sub(r'\s+','',common)
        if not all(token in compact for token in required):return result
    # Uc is the effective button subclass. Reject an unknown member that could
    # replace its inherited event/dispatch contract; do not trust a base token
    # merely because it still exists elsewhere in the bundle.
    button=_methods(common, marker='Uc=Eba.extend({', reject_slashes=False)
    known_button={'cR','Ia','nbc','j3h','S3h','vgf','Dr','xpp','kdx','Fte','py','wlb','Xn','Y8e','Oie','e9e'}
    if set(button)!=known_button or compact.count('Uc=Eba.extend({')!=1:return result
    if 'wc.Xoe(a.RJb,a.Du,function(){a.qa(!0)})' not in button.get('Ia',''):return result

    constructor=re.search(r'new\s*\(xd\.extend\(\{',client)
    anonymous=_methods(client[constructor.start():],include_end=True) if constructor else {}
    if (isinstance(anonymous,tuple) and _top_level_prefix(client[:constructor.start()])
            and re.match(r'\)\s*\)\s*(?:;|$)',client[constructor.start()+anonymous[1]:])
            and re.fullmatch(r'"undefined"===typeof(?P<arg>[A-Za-z_$][\w$]*)\?\(this\._super\(null\),[A-Za-z_$][\w$]*\.Bb\(\)\.Gg\("'
                +re.escape(symbol)+r'",this\)\):this\._super\((?P=arg)\)',anonymous[0].get('ctor',''))):
        methods=anonymous[0]
    else:
        candidates=[]
        for assigned in re.finditer(r'\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*xd\.extend\(\{',client):
            prefix=re.sub(r'\s+','',client[:assigned.start()])
            if prefix not in {'','"usestrict";',"'usestrict';"}:continue
            fragment=client[assigned.start():]
            parsed=_methods(fragment,include_end=True)
            if not isinstance(parsed,tuple):continue
            descriptor,end=parsed
            # The live descriptor is constructed and registered immediately;
            # a declaration, unrelated subclass or intervening rebinding is not
            # an authoritative absence declaration.
            if (re.match(r'\)\s*;\s*new\s+'+re.escape(assigned[1])+r'\s*(?:;|\(\s*\)\s*;)',fragment[end:])
                    and re.fullmatch(r'"undefined"===typeof(?P<arg>[A-Za-z_$][\w$]*)\?\(this\._super\(null\),[A-Za-z_$][\w$]*\.Bb\(\)\.Gg\("'
                        +re.escape(symbol)+r'",this\)\):this\._super\((?P=arg)\)',descriptor.get('ctor',''))):
                candidates.append(descriptor)
        if len(candidates)!=1:return result
        methods=candidates[0]
    if not methods:return result
    if methods.get('Ya','returnce.create(this.Cc(),this.la)') != 'returnce.create(this.Cc(),this.la)':return result
    if 'Oia' in methods and methods['Oia'] not in {'returnnewUc','returnthis.oda()?newEba:null'}:return result
    if 't$a' not in methods:
        result['domains']['ante']={'complete':True,'source':SOURCE,'options':[]}
    flag=methods.get('oda','return!1')
    if flag=='return!1':
        result['domains']['purchase']={'complete':True,'source':SOURCE,'options':[]}
        return result
    if flag!='return!v.tS()&&!v.uoa' or type(initial.get('dbf')) is not bool:return result
    if initial['dbf']:
        result['domains']['purchase']={'complete':True,'source':SOURCE,'options':[]}
        return result
    cost=re.fullmatch(r'return([0-9]+)\*this\.Tc\([\w,]+\)', methods.get('Xqa',''))
    if not cost or int(cost[1])<=0:return result
    result['domains']['purchase']={'complete':True,'source':SOURCE,'options':['pos:1']}
    result['modes']=[{'id':'BUY_POS_1','kind':'PURCHASE','pos':[1], 'source':'client-declaration',
        'observed':True,'validated':False,'executable':False,'coverage_required':True,
        'required_options':['pos:1'],'covered_options':[], 'cost_multiplier':int(cost[1]),
        'request_shape':{'pos':[1]},'declaration_source':SOURCE}]
    return result
