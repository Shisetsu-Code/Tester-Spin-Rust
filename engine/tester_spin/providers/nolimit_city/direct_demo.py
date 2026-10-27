"""Source-bound exclusion of the developer-only local response playback UI.

The caller must independently attest a fresh direct demo transport. Wire fields
never supply this context, and ordinary imported captures remain conservative.
"""
import re
from functools import lru_cache
from .static_bindings import class_record,IDENT


def members(body,block):
    result={};cursor=1
    while cursor<len(body)-1:
        match=re.match(r'(?:(get|set) )?('+IDENT+r')\(([^)]*)\)\{',body[cursor:])
        if not match:return None
        value=block(body,cursor+match.end()-1)
        if not value:return None
        key=(match[1]+' ' if match[1] else '')+match[2]
        if key in result:return None
        result[key]=(match[3],value[1:-1]);cursor+=match.end()-1+len(value)
    return result


def local_playback_contract(source,position,receiver,block):
    game=class_record(source,position,receiver,block)
    if not game:return False
    prefix=source[max(0,game[2]-200):game[2]]
    named=re.search(r'class ('+IDENT+r')(?: extends '+IDENT+r'\.'+IDENT+r')?$',prefix)
    if not named:return False
    assignments=list(re.finditer(re.escape(named[1])+r'\.localReplay=new ('+IDENT+r'\.'+IDENT+r')\('+re.escape(named[1])+r'\.apiPlugin(?=[,)])',game[0]))
    if len(assignments)!=1:return False
    # Validate the object identity throughout its defining module, including
    # static writes after the class declaration and exported/local aliases.
    headers=list(re.finditer(r'(?:^|[,{])([0-9]+(?:e[0-9]{1,3})?)(?::function|:)?\(('+IDENT+r'),('+IDENT+r')(?:,('+IDENT+r'))?\)(?:=>)?\{',source))
    owners=[header for header in headers if header.end()<=game[2]]
    if not owners:return False
    owner=owners[-1];module=block(source,owner.end()-1,len(source))
    if not module:return False
    aliases={named[1]}
    exported=re.escape(owner[3])+r'\.'+IDENT
    aliases.update(match[1] for match in re.finditer(r'('+exported+r')='+re.escape(named[1])+r'(?=[,;}])',module))
    for _ in range(5):
        references='(?:'+'|'.join(re.escape(alias) for alias in aliases)+')'
        discovered={match[1] for match in re.finditer(r'(?<![\w$.])('+IDENT+r')='+references+r'(?=[,;}])',module)}
        if discovered<=aliases:break
        aliases.update(discovered)
    references='(?:'+'|'.join(re.escape(alias) for alias in aliases)+')'
    writes=list(re.finditer(r'(?<![\w$.])'+references+r'(?:\.localReplay|\[["\']localReplay["\']\])\s*=(?!=)',module))
    if len(writes)!=1:return False
    definition=class_record(source,game[2]+assignments[0].start(),assignments[0][1],block)
    if not definition:return False
    available=members(definition[0],block)
    if not available or available.get('get isPlaying')!=('', 'return this.replaying') or 'set isPlaying' in available:return False
    fake=available.get('sendFakeBet')
    shape=r'[\w$.]+\.apiPlugin\.events\.trigger\("bet",\{type:"FAKE_BET",bet:"0\.00",isFakeBet:!0,replayAndFeatureBuy:!0,requestNextResponse:!0\}\)'
    if not fake or fake[0] or not re.fullmatch(shape,fake[1]):return False
    constructor=available.get('constructor');playback=available.get('startPlayback')
    if not constructor or not playback:return False
    if not re.search(r'this\.replaying=!1(?=[,;)])',constructor[1]):return False
    if 'this.startReplayButton.addClickCallback(()=>this.startPlayback())' not in constructor[1]:return False
    if len(re.findall(r'this\.startPlayback\(',definition[0]))!=1:return False
    if not re.search(r'this\.recordedResponses\.length<=0\|\|\(',playback[1]) or not playback[1].endswith('this.sendInitialBet())'):return False
    if len(re.findall(r'this\.replaying=!0(?=[,;)])',playback[1]))!=1:return False
    # Only explicit UI playback activates the state. The constructor/readyState
    # paths may reset it; any other state assignment invalidates this contract.
    for name,(args,body) in available.items():
        writes=re.findall(r'this\.replaying=(?!=)([^,;)]+)',body)
        if name=='startPlayback':
            if writes!=['!0']:return False
        elif any(value!='!1' for value in writes):return False
    return True


@lru_cache(maxsize=2)
def direct_demo_source(source,block):
    """Select ELSE only for the verified developer local-playback condition."""
    from .lifecycle import conditional_arms
    matches=list(re.finditer(r'('+IDENT+r'\.'+IDENT+r')\.localReplay\.isPlaying\?',source))
    replacements=[]
    for match in matches:
        if match.start() and source[match.start()-1] not in '{(,;':continue
        if not local_playback_contract(source,match.start(),match[1],block):continue
        stack=[];quote=None;escaped=False;end=match.end()
        while end<len(source):
            char=source[end]
            if quote:
                if escaped:escaped=False
                elif char=='\\':escaped=True
                elif char==quote:quote=None
            elif char in ('"',"'",'`'):quote=char
            elif char in '([{':stack.append(char)
            elif char in ')]}':
                if not stack:break
                if '([{'.index(stack.pop())!=')]}'.index(char):break
            elif not stack and char in ',;':break
            end+=1
        arms=conditional_arms(source[match.start():end])
        if arms:replacements.append((match.start(),end,arms[1]))
    for start,end,value in reversed(replacements):source=source[:start]+value+source[end:]
    return source
