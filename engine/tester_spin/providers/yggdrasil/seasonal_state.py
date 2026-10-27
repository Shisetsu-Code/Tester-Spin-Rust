"""Season-to-reel roles learned from the client, contrasted with server strips."""
ROLES={'SPRING':'ReelsWalking','SUMMER':'ReelsPlus','FALL':'ReelsMultiplier','WINTER':'ReelsWonky'}

def declaration(props):
    width=props.get('NumberOfReels')
    if type(width) is not int or not 1<=width<=20:return None
    for name in list(ROLES.values())+['Feature'+v for v in ROLES.values()]:
        strips=props.get(name)
        if not isinstance(strips,list) or len(strips)!=width:return None
        if any(not isinstance(col,list) or not 1<=len(col)<=65536 or any(not isinstance(v,str) or not 1<=len(v)<=128 for v in col) for col in strips):return None
    return dict(ROLES)

def neutral(ed,constraints):
    if not isinstance(ed,dict) or not {'currentSeason','numberOfSpins'}<=set(ed):return False
    domain=(constraints or {}).get('season_reels')
    return (domain==ROLES and isinstance(ed['currentSeason'],str)
            and ed['currentSeason'] in domain and ed.get('reelSet')==domain[ed['currentSeason']]
            and type(ed['numberOfSpins']) is int and 0<=ed['numberOfSpins']<=1000000)
