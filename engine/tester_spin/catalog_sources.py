"""Public catalog authorities shared by GUI, CLI and update packages."""
SOURCES = {
 'playtech': {'name':'Playtech','class':'PlaytechProvider','url':'https://www.playtechone.com/','hosts':['www.playtechone.com'],'kind':'playtech'},
 'games_global': {'name':'Games Global','class':'GamesGlobalProvider','url':'https://www.gamesglobal.com/Products','hosts':['www.gamesglobal.com'],'kind':'global'},
 'amusnet': {'name':'Amusnet','class':'AmusnetProvider','url':'https://amusnet.com/online-casino','hosts':['amusnet.com','www.amusnet.com','amusnetgaming.com'],'kind':'amusnet','feed':'https://amusnetgaming.com/online-casino'},
 'playngo': {'name':"Play’n GO",'class':'PlayNGoProvider','url':'https://www.playngo.com/games','hosts':['www.playngo.com'],'kind':'playngo'},
 'greentube': {'name':'Greentube / Novomatic','class':'GreentubeProvider','url':'https://www.greentube.com/all-games/','hosts':['www.greentube.com'],'kind':'greentube'},
 'netent': {'name':'NetEnt','class':'NetEntProvider','url':'https://netent.com/games','hosts':['netent.com'],'kind':'netent'},
 'pgsoft': {'name':'PG Soft','class':'PGSoftProvider','url':'https://www.pgsoft.com/games/home/','hosts':['www.pgsoft.com'],'kind':'pgsoft'},
 'blueprint': {'name':'Blueprint Gaming','class':'BlueprintProvider','url':'https://blueprintgaming.com/games','hosts':['blueprintgaming.com'],'kind':'blueprint'},
 'relax': {'name':'Relax Gaming','class':'RelaxProvider','url':'https://www.relax-gaming.com/products/own-games','hosts':['www.relax-gaming.com'],'kind':'html','pattern':r'^/products/casino/[^/]+/?$'},
 'playson': {'name':'Playson','class':'PlaysonProvider','url':'https://www.playson.com/en/games','hosts':['www.playson.com','playson.com','m.playson.com'],'kind':'html','feed':'https://m.playson.com/games','pattern':r'^/(?:en/)?game/[^/]+/?$'},
 'wazdan': {'name':'Wazdan','class':'WazdanProvider','url':'https://wazdan.com/games','hosts':['wazdan.com'],'kind':'sitemap','feed':'https://wazdan.com/games-sitemap.xml','pattern':r'^/games/[^/]+/?$'},
 'elk': {'name':'ELK Studios','class':'ELKProvider','url':'https://www.elk-studios.com/games/','hosts':['www.elk-studios.com'],'kind':'html','pattern':r'^/games/[^/]+/?$'},
 'pushgaming': {'name':'Push Gaming','class':'PushGamingProvider','url':'https://www.pushgaming.com/games/','hosts':['www.pushgaming.com'],'kind':'html','pattern':r'^/games/[^/]+\.html$'},
}
