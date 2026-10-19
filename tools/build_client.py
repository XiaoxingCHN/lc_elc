"""Build a disposable client worktree; never overwrite a published release."""
import argparse,datetime,json,os,platform,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def plan(a):
 host='windows' if os.name=='nt' else 'linux'
 flutter=Path(a.flutter) if a.flutter else ROOT/'dependencies/sdk'/host/'flutter/bin'/('flutter.bat' if os.name=='nt' else 'flutter')
 if flutter.is_dir():flutter=flutter/'bin'/('flutter.bat' if os.name=='nt' else 'flutter')
 cache=Path(a.pub_cache) if a.pub_cache else ROOT/('dependencies/pub-cache-'+host)
 commands=[[str(flutter),'pub','get','--enforce-lockfile']+([] if a.online else ['--offline'])]
 if a.test:commands.append([str(flutter),'test','--no-pub'])
 if not a.test_only:commands.append([str(flutter),'build','apk' if a.platform=='android' else a.platform,'--release','--no-pub','--dart-define=LAB_ODOO_URL='+a.server,'--dart-define=LAB_ODOO_DB='+a.database])
 return host,flutter,cache,commands

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--platform',choices=['windows','android','linux'],required=True);p.add_argument('--flutter');p.add_argument('--pub-cache');p.add_argument('--android-sdk');p.add_argument('--jdk');p.add_argument('--signing-key');p.add_argument('--gradle-cache');p.add_argument('--server',default='http://192.168.31.105:8069');p.add_argument('--database',default='LcHardwareHouse');p.add_argument('--online',action='store_true');p.add_argument('--test',action='store_true');p.add_argument('--test-only',action='store_true');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
 if a.test_only:a.test=True
 host,flutter,cache,commands=plan(a)
 print(json.dumps({'source':'clients/app','host':host,'platform':a.platform,'pub_cache':str(cache),'commands':commands,'writes':'new timestamp directory under local/build; no release overwrite'},ensure_ascii=False,indent=2))
 if a.dry_run:return
 if a.platform=='windows' and os.name!='nt':p.error('Windows native build must run on Windows')
 if a.platform=='linux' and platform.system()!='Linux':p.error('Linux native build must run on Linux/WSL; see clients/linux/README.md')
 if not flutter.is_file():p.error('Flutter missing; restore dependencies first, see dependencies/README.md')
 if host=='linux' and not a.flutter and (ROOT/'dependencies/sdk/linux/EXPANDED_ON_WINDOWS_INCOMPLETE.txt').exists():p.error('Restore the preserved Linux SDK tar or WSL tool archive onto a Linux filesystem and pass --flutter explicitly; the Windows-expanded Linux SDK is not a complete runtime.')
 stamp=datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f');work=ROOT/'local/build'/('client-'+a.platform+'-'+stamp);work.mkdir(parents=True)
 src=work/'source';shutil.copytree(ROOT/'clients/app',src,ignore=shutil.ignore_patterns('.dart_tool','build','ephemeral','.gradle','.cxx','.idea','local.properties','.flutter-plugins-dependencies','*.iml','GeneratedPluginRegistrant.java'))
 env=os.environ.copy();env['PUB_CACHE']=str(cache);env['CMAKE_BUILD_PARALLEL_LEVEL']='2';env['FLUTTER_SUPPRESS_ANALYTICS']='true';env['GRADLE_OPTS']='-Dorg.gradle.workers.max=2 -Dorg.gradle.parallel=false';env['GRADLE_USER_HOME']=str(Path(a.gradle_cache).resolve() if a.gradle_cache else ROOT/'dependencies/gradle-cache');env['PATH']=str(flutter.parent)+os.pathsep+env.get('PATH','')
 if a.platform=='android':
  sdk=Path(a.android_sdk) if a.android_sdk else ROOT/'dependencies/android/sdk';jdk=Path(a.jdk) if a.jdk else ROOT/'dependencies/android/java'
  # Restored archives may contain one JDK subdirectory; choose only unambiguous layout.
  if not (jdk/'bin').exists():
   children=[q for q in jdk.glob('*') if (q/'bin').is_dir()]
   if len(children)==1:jdk=children[0]
  if not sdk.exists() or not (jdk/'bin').exists():p.error('Android SDK/JDK missing; pass --android-sdk/--jdk or restore offline toolchain')
  key=Path(a.signing_key) if a.signing_key else ROOT/'local/private/signing/windows-debug.keystore'
  if not key.is_file():p.error('Signing key missing. Existing installs require the recorded signing identity; no automatic new key generation.')
  private=work/'android-user';private.mkdir();shutil.copy2(key,private/'debug.keystore')
  env.update(JAVA_HOME=str(jdk),ANDROID_HOME=str(sdk),ANDROID_SDK_ROOT=str(sdk),ANDROID_USER_HOME=str(private));env['PATH']=str(jdk/'bin')+os.pathsep+env['PATH']
  # Forward slashes avoid Java properties escaping; no credentials are written here.
  (src/'android/local.properties').write_text('sdk.dir='+sdk.as_posix()+'\nflutter.sdk='+flutter.parent.parent.as_posix()+'\n',encoding='utf-8')
 results=[]
 for index,cmd in enumerate(commands):
  logfile=work/(str(index)+'-command.log')
  with logfile.open('wb') as output:r=subprocess.run(cmd,cwd=src,env=env,stdout=output,stderr=subprocess.STDOUT)
  results.append({'command':cmd,'exit_code':r.returncode,'log':str(logfile.relative_to(ROOT))});(work/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print('exit='+str(r.returncode)+' log='+str(logfile))
  if r.returncode:
   if os.name=='nt':print('If plugin symlink permissions caused failure, use dependencies/ensure_plugin_junctions.ps1 with -Project and -PubCache on THIS worktree, then rerun in it. Do not enable global developer settings automatically.')
   raise SystemExit(r.returncode)
 if not a.test_only and a.platform in ('windows','linux'):
  from prepare_client_update import prepare
  if a.platform=='linux':bundle=src/'build/linux/x64/release/bundle'
  else:
   candidates=list((src/'build/windows').glob('*/runner/Release'))
   if len(candidates)!=1:raise RuntimeError('Expected one Windows release bundle')
   bundle=candidates[0]
  dart=flutter.parent/'cache/dart-sdk/bin'/('dart.exe' if os.name=='nt' else 'dart')
  prepare(src,bundle,dart,a.platform)
 print('Build/test completed. Inspect '+str(work)+'; register a new immutable release after platform acceptance.')
if __name__=='__main__':main()
