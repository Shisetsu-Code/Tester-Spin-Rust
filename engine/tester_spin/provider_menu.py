"""Console menu distributed with the same runtime as the desktop interface."""
import ctypes,os
from pathlib import Path
from tester_spin.cli import main
from tester_spin.providers.registry import PROVIDERS,create_provider

def menu():
 data_root=Path(os.environ.get('TESTER_SPIN_DATA_ROOT','data'))
 choices=list(PROVIDERS)
 for number,key in enumerate(choices,1):print(f'{number}. {PROVIDERS[key][2]}')
 try:
  number=int(input('Número de proveedor: '))
  if not 1<=number<=len(choices):raise ValueError('Proveedor inválido')
  key=choices[number-1];provider=create_provider(key,data_root)
  if not getattr(provider,'execution_supported',True):
   print('Este proveedor tiene catálogo; el ejecutor todavía está pendiente.')
   return main(['catalog',key,'--data-root',str(data_root)])
  limit=int(input('Cantidad total de juegos (0 = todos): '))
  args=['run',key,'--data-root',str(data_root),'--limit',str(limit)]
  if input('¿Usar WireGuard? (s/n): ').strip().casefold()=='s':
   folder=input('Carpeta de archivos .conf exportados: ').strip()
   if not folder:raise ValueError('Falta la carpeta WireGuard; no se ejecutará por red directa')
   if os.name=='nt' and not ctypes.windll.shell32.IsUserAnAdmin():raise ValueError('Para WireGuard, abrí el acceso como administrador')
   quota=int(input('Cantidad máxima de juegos por IP: '))
   args+=['--wg-dir',folder,'--games-per-ip',str(quota)]
  return main(args)
 except (ValueError,EOFError) as exc:
  print(str(exc));return 2

if __name__=='__main__':
 try:code=menu()
 except KeyboardInterrupt:code=130
 try:input('Presioná Enter para cerrar')
 except (EOFError,KeyboardInterrupt):pass
 raise SystemExit(code)
