"""Configured scatter replacements and an explicit walking-symbol position."""
from .named_actions import _board,_number

def declaration(props):
    if not isinstance(props,dict):return None
    icons=props.get('Icons');banned=props.get('EdgeScattersIsColumnBanned');replacement=props.get('EdgeScattersReplacementIcon');strips=props.get('BaseReels');supplier=props.get('BaseReelsSupplierConfig')
    if not isinstance(icons,list) or not 1<=len(icons)<=256 or any(not isinstance(v,str) or not 1<=len(v)<=128 for v in icons) or len(set(icons))!=len(icons) or not {'SCATTER','WALKING_WILD'}<=set(icons):return None
    if not isinstance(replacement,str) or replacement not in icons or replacement in {'SCATTER','WALKING_WILD'}:return None
    if not isinstance(banned,list) or not 1<=len(banned)<=20 or any(type(v) is not bool for v in banned) or not any(banned):return None
    if not isinstance(strips,list) or not 1<=len(strips)<=64 or any(not isinstance(col,list) or not 1<=len(col)<=65536 or any(v not in icons for v in col) for col in strips):return None
    if not isinstance(supplier,dict):return None
    table=supplier.get('baseReelsTable')
    if not isinstance(table,list) or not 1<=len(table)<=256 or any(not isinstance(row,list) or len(row)!=len(banned) or any(type(v) is not int or not 0<=v<len(strips) for v in row) for row in table):return None
    return {'icons':icons,'banned_columns':banned,'replacement':replacement,'base_reels':list(dict.fromkeys('BaseReels_'+'_'.join(map(str,row)) for row in table))}

def valid_output(ed,constraints):
    try:
        definition=(constraints or {}).get('edge_replacement')
        if not isinstance(definition,dict) or set(definition)!={'icons','banned_columns','replacement','base_reels'} or ed.get('reelSet') not in definition['base_reels']:return False
        board=ed['reels'];final=ed['finalBoard']
        if not _board(board) or len(board)!=len(definition['banned_columns']) or len({len(c) for c in board})!=1 or not _board(final) or [len(c) for c in final]!=[len(c) for c in board]:return False
        if any(v not in definition['icons'] for col in board+final for v in col):return False
        data=ed['spinData']
        if not isinstance(data,dict) or set(data)!={'featuresOutputs','multiplier'} or not _number(data['multiplier'],positive=True):return False
        effects=data['featuresOutputs']
        if not isinstance(effects,dict) or 'edgeScatters' not in effects or not set(effects)<={'edgeScatters','walkingWild'}:return False
        replacements=effects['edgeScatters']
        if not isinstance(replacements,dict) or not 1<=len(replacements)<=len(board):return False
        expected=[list(col) for col in board]
        for key,value in replacements.items():
            if not isinstance(key,str) or not key.isdecimal() or str(int(key))!=key or not 0<=int(key)<len(board) or not definition['banned_columns'][int(key)] or value!=definition['replacement']:return False
            column=int(key);changed=False
            for row,symbol in enumerate(board[column]):
                if symbol=='SCATTER':expected[column][row]=value;changed=True
            if not changed:return False
        if 'walkingWild' in effects:
            move=effects['walkingWild']
            if not isinstance(move,dict) or set(move)!={'positionBefore','positionAfter'}:return False
            for position in move.values():
                if not isinstance(position,dict) or set(position)!={'reel','row'} or type(position['reel']) is not int or type(position['row']) is not int or not 0<=position['reel']<len(board) or not 0<=position['row']<len(board[position['reel']]):return False
            position=move['positionAfter'];expected[position['reel']][position['row']]='WALKING_WILD'
        return expected==final
    except (KeyError,TypeError,ValueError,AttributeError):return False
