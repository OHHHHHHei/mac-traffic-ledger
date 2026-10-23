#!/usr/bin/env python3
import os,pathlib,plistlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parent
LABEL='local.traffic-ledger'
PLIST=pathlib.Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
DATA=pathlib.Path.home()/'Library/Application Support/LocalTrafficLedger'
TARGET=f'gui/{os.getuid()}'
def main():
 cmd=sys.argv[1] if len(sys.argv)>1 else 'status'
 if cmd=='install':
  DATA.mkdir(parents=True,exist_ok=True);PLIST.parent.mkdir(parents=True,exist_ok=True)
  content={'Label':LABEL,'ProgramArguments':[sys.executable,'-m','mac_traffic_ledger.ledger'],'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'StandardOutPath':str(DATA/'service.log'),'StandardErrorPath':str(DATA/'error.log'),'EnvironmentVariables':{'PYTHONUNBUFFERED':'1','PYTHONPATH':str(ROOT.parent)}}
  subprocess.run(['launchctl','bootout',TARGET+'/'+LABEL],capture_output=True)
  PLIST.write_bytes(plistlib.dumps(content))
  for attempt in range(12):
   result=subprocess.run(['launchctl','bootstrap',TARGET,str(PLIST)],capture_output=True,text=True)
   if result.returncode==0:break
   time.sleep(.25)
  else:raise SystemExit(result.stderr)
  print('Installed: http://127.0.0.1:8766')
 elif cmd in ['stop','uninstall']:
  subprocess.run(['launchctl','bootout',TARGET+'/'+LABEL],capture_output=True)
  if cmd=='uninstall':PLIST.unlink(missing_ok=True)
  print('Stopped. Historical database retained at',DATA)
 elif cmd=='start':subprocess.run(['launchctl','bootstrap',TARGET,str(PLIST)],check=True)
 elif cmd=='status':subprocess.run(['launchctl','print',TARGET+'/'+LABEL])
 else:raise SystemExit('Use: install | start | stop | uninstall | status')

if __name__ == "__main__":
 main()
