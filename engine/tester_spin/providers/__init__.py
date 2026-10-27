"""Compatible lazy exports and standalone selection from one shared registry."""
import os
from tester_spin.providers.base import ProviderAdapter,ProviderRegistry
from tester_spin.providers.registry import PROVIDERS,provider_class

__all__=['ProviderAdapter','ProviderRegistry','selected_provider_keys']+[value[1] for value in PROVIDERS.values()]

def selected_provider_keys():
 return tuple(dict.fromkeys(part.strip().lower() for part in os.environ.get('TESTER_SPIN_PROVIDER_ONLY','').split(',') if part.strip()))

def __getattr__(name):
 for key,(_,class_name,_) in PROVIDERS.items():
  if class_name==name:
   value=provider_class(key);globals()[name]=value;return value
 raise AttributeError(name)

def __dir__():return sorted(set(globals())|set(__all__))
