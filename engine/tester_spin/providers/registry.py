"""Provider identities without importing their implementations."""
from importlib import import_module

PROVIDERS={
 'pragmatic':('pragmatic_farm_adapter','PragmaticProvider','Pragmatic Play'),
 '1spin4win':('one_spin4win_farm_adapter','OneSpin4WinProvider','1Spin4Win'),
 'belatra':('belatra_farm_adapter','BelatraProvider','Belatra'),
 'bgaming':('bgaming_farm_adapter','BGamingProvider','BGaming'),
 'ka_gaming':('ka_gaming.farm_adapter','KAGamingProvider','KA Gaming'),
 'rubyplay':('rubyplay.farm_adapter','RubyPlayProvider','RubyPlay'),
 'redtiger':('redtiger.farm_adapter','RedTigerProvider','Red Tiger'),
 '3oaks':('three_oaks','ThreeOaksProvider','3 Oaks'),
 'yggdrasil':('yggdrasil','YggdrasilProvider','Yggdrasil'),
 'hacksaw':('hacksaw','HacksawProvider','Hacksaw Gaming'),
 'nolimit_city':('nolimit_city','NolimitCityProvider','Nolimit City'),
}

from tester_spin.catalog_sources import SOURCES
PROVIDERS.update({key:('catalogs.adapter',spec['class'],spec['name']) for key,spec in SOURCES.items()})
PROVIDERS['playtech']=('playtech.adapter','PlaytechProvider','Playtech')
PROVIDERS['pushgaming']=('pushgaming','PushGamingProvider','Push Gaming')
PROVIDERS['relax']=('relax','RelaxProvider','Relax Gaming')
PROVIDERS['elk']=('elk','ElkProvider','ELK Studios')
PROVIDERS['playson']=('playson','PlaysonProvider','Playson')
PROVIDERS['games_global']=('games_global','GamesGlobalProvider','Games Global')
PROVIDERS['playngo']=('playngo','PlayNGoProvider',"Play'n GO")
PROVIDERS['amusnet']=('amusnet','AmusnetProvider','Amusnet')

def provider_class(key):
 if key not in PROVIDERS:raise ValueError('Proveedor no registrado: '+str(key))
 module,name,_=PROVIDERS[key]
 return getattr(import_module('tester_spin.providers.'+module),name)

def create_provider(key,data_root):return provider_class(key)(data_root)
