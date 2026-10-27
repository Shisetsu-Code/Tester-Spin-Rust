"""Launch the independent CLI from exactly the GUI updater's active runtime."""
import os
import subprocess,sys
from pathlib import Path

def cli_command(python_exe,app_dir,env,args):
 python=Path(python_exe)
 if python.name.casefold()=='pythonw.exe':python=python.with_name('python.exe')
 environment=dict(env)
 environment['PYTHONPATH']=str(Path(app_dir))+os.pathsep+environment.get('PYTHONPATH','')
 environment['PYTHONUTF8']='1';environment['PYTHONIOENCODING']='utf-8'
 return [str(python),'-m','tester_spin.cli',*args],environment

def main(argv=None):
 from tester_spin.updater import Updater
 updater=Updater();app=updater.prepare_runtime(lambda message:print(message,file=sys.stderr))
 python,env=updater.ensure_environment(app,lambda message:print(message,file=sys.stderr))
 args=list(sys.argv[1:] if argv is None else argv)
 command,environment=cli_command(python,app,env,args)
 if args==['--menu']:command=command[:1]+['-m','tester_spin.provider_menu']
 return subprocess.call(command,cwd=str(app),env=environment)

if __name__=='__main__':raise SystemExit(main())
