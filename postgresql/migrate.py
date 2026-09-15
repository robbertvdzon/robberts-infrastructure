#!/usr/bin/env python3
"""Operator-only migration runner. Binary backups and credentials stay in private storage.
Commands: prepare, probe <key>, migrate <key>, start <key>, resume-gitops.
Requires explicit production migration authorization; never run as an AI worker job.
"""
import base64,hashlib,json,os,secrets,subprocess,sys,time
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT.parent
PRIVATE=Path.home()/'.local/share/postgresql-consolidation/20260915';os.umask(0o077)
STATE=json.loads((PRIVATE/'state.json').read_text())
MAP={
'hkh_acc':('hkh-acceptance','hkh','deploy/overlays/acceptance','backend','hkh','statefulset','database','nonproduction','HKH_DATABASE_URL','HKH_DATABASE_USER','HKH_DATABASE_PASSWORD'),
'hkh_prod':('hkh','hkh','deploy/overlays/openshift','backend','hkh','statefulset','database','production','HKH_DATABASE_URL','HKH_DATABASE_USER','HKH_DATABASE_PASSWORD'),
'hkh_autopilot_acc':('hkh-autopilot-acceptance','hkh-autopilot','deploy/overlays/acceptance','backend','hkh','statefulset','database','nonproduction','HKH_DATABASE_URL','HKH_DATABASE_USER','HKH_DATABASE_PASSWORD'),
'hkh_autopilot_prod':('hkh-autopilot','hkh-autopilot','deploy/overlays/openshift','backend','hkh','statefulset','database','production','HKH_DATABASE_URL','HKH_DATABASE_USER','HKH_DATABASE_PASSWORD'),
'pvdd_acc':('pvdd-acceptance','pvdd','deploy/overlays/acceptance','backend','pvdd','statefulset','database','nonproduction','PVDD_DATABASE_URL','PVDD_DATABASE_USER','PVDD_DATABASE_PASSWORD'),
'pvdd_prod':('pvdd','pvdd','deploy/overlays/production','backend','pvdd','statefulset','database','production','PVDD_DATABASE_URL','PVDD_DATABASE_USER','PVDD_DATABASE_PASSWORD'),
'pf_prod':('product-factory','product-factory','deploy/overlays/production','product-factory-backend','productfactory_v2','deployment','product-factory-postgres','production','PF_DB_URL','PF_DB_USERNAME','PF_DB_PASSWORD'),
'pf_legacy_prod':('product-factory','product-factory','deploy/overlays/production',None,'productfactory','deployment','postgres','production',None,None,None),
'sf_prod':('software-factory','softwarefactory','deploy/base','software-factory-backend','software_factory','statefulset','database','production','SF_DATABASE_URL','SF_DATABASE_USER','SF_DATABASE_PASSWORD'),
'ar_prod':('agent-runtime','agent-runtime','deploy/production','agent-runtime-server','agent_runtime','deployment','postgres','production','AR_DB_URL','AR_DB_USERNAME','AR_DB_PASSWORD'),
'pf_acc':('product-factory-acceptance','product-factory','deploy/overlays/acceptance','product-factory-backend',None,None,None,'nonproduction','PF_DB_URL','PF_DB_USERNAME','PF_DB_PASSWORD'),
'ar_acc':('agent-runtime-acceptance','agent-runtime','deploy/acceptance','agent-runtime-server',None,None,None,'nonproduction','AR_DB_URL','AR_DB_USERNAME','AR_DB_PASSWORD'),
}
def log(event,**fields):print(json.dumps({'event':event,**fields}),flush=True)
def run(args,*,data=None,stdin=None,stdout=None,timeout=600):
 p=subprocess.run(args,input=data,stdin=stdin,stdout=stdout or subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 if p.returncode:
  # Store diagnostic privately. Never forward database row details or secrets to the model.
  (PRIVATE/'last-error.txt').write_bytes(p.stderr)
  raise RuntimeError(f'{args[0]} failed (exit {p.returncode}); private diagnostic saved')
 return p.stdout or b''
def oc(*args):return run(['oc',*args])
def get(kind,name,ns):return json.loads(oc('get',kind,name,'-n',ns,'-o','json'))
def sql(ns,pod,db,statement):return run(['oc','exec','-i','-n',ns,pod,'--','psql','-X','-qAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],data=statement.encode()).decode().strip()
def ident(s):
 if not s.replace('_','').isalnum() or len(s)>63:raise ValueError('invalid identifier')
 return '"'+s+'"'
def source_pod(m):
 ns,_,_,_,db,kind,workload,*_=m
 w=get(kind,workload,ns);selector=','.join(k+'='+v for k,v in w['spec']['selector']['matchLabels'].items())
 pods=json.loads(oc('get','pods','-n',ns,'-l',selector,'-o','json'))['items']
 return next(p['metadata']['name'] for p in pods if p['status']['phase']=='Running')
def metadata(ns,pod,db):
 statement="""BEGIN READ ONLY;
SELECT coalesce(json_agg(t),'[]') FROM (SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2)t;
COMMIT;"""
 tables=json.loads(sql(ns,pod,db,statement));counts={}
 for table in tables:
  sc=table['schemaname'];t=table['tablename']
  counts[sc+'.'+t]=int(sql(ns,pod,db,f'BEGIN READ ONLY;SELECT count(*) FROM {ident(sc)}.{ident(t)};COMMIT;'))
 schema='software_factory' if 'software_factory.flyway_schema_history' in counts else 'public'
 history=json.loads(sql(ns,pod,db,f"BEGIN READ ONLY;SELECT coalesce(json_agg(t),'[]') FROM (SELECT version,type,success,checksum FROM {ident(schema)}.flyway_schema_history ORDER BY installed_rank)t;COMMIT;"))
 sequences=json.loads(sql(ns,pod,db,"BEGIN READ ONLY;SELECT coalesce(json_agg(t),'[]') FROM (SELECT schemaname,sequencename,last_value FROM pg_sequences WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2)t;COMMIT;"))
 return {'counts':counts,'flyway':history,'sequences':sequences}
def secret_ref(name,key):return {'name':name,'value':None,'valueFrom':{'configMapKeyRef':None,'secretKeyRef':{'name':'central-postgres','key':key}}}
def prepare():
 for key,m in MAP.items():
  ns,repo,overlay,backend,db,kind,old,tier,urlvar,uservar,passvar=m
  folder=WORK/repo/overlay;kpath=folder/'kustomization.yaml';k=yaml.safe_load(kpath.read_text())
  if backend:
   dep=get('deployment',backend,ns);container=dep['spec']['template']['spec']['containers'][0]['name']
   password=STATE[tier][key];host='postgres.postgres-'+tier+'.svc';url=f'jdbc:postgresql://{host}:5432/{key}?sslmode=verify-full&sslrootcert=/etc/postgres-ca/ca.crt'
   values={'username':key,'password':password,'url':url,'ca.crt':(PRIVATE/(tier+'.crt')).read_text()}
   if key=='sf_prod':values['custom-url']=f'postgresql://{key}:{password}@{host}:5432/{key}?sslmode=verify-full&sslrootcert=/etc/postgres-ca/ca.crt'
   secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'central-postgres','namespace':ns},'type':'Opaque','data':{a:base64.b64encode(b.encode()).decode() for a,b in values.items()}}
   (PRIVATE/(key+'-secret.json')).write_text(json.dumps(secret))
   sealed=run(['/opt/homebrew/bin/kubeseal','--cert',str(PRIVATE/'sealed-secrets.crt'),'--scope','strict','--format','yaml'],data=json.dumps(secret).encode())
   (folder/'sealed-central-postgres.yaml').write_bytes(sealed)
   env=[secret_ref(urlvar,'custom-url' if key=='sf_prod' else 'url'),secret_ref(uservar,'username'),secret_ref(passvar,'password')]
   env += [secret_ref('SPRING_DATASOURCE_URL','url'),secret_ref('SPRING_DATASOURCE_USERNAME','username'),secret_ref('SPRING_DATASOURCE_PASSWORD','password'),{'name':'SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE','value':'5'},{'name':'SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE','value':'1'}]
   patch={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':backend},'spec':{'template':{'metadata':{'labels':{'postgres.vdzonsoftware.nl/client':'true'}},'spec':{'containers':[{'name':container,'env':env,'volumeMounts':[{'name':'central-postgres-ca','mountPath':'/etc/postgres-ca','readOnly':True}]}],'volumes':[{'name':'central-postgres-ca','secret':{'secretName':'central-postgres','items':[{'key':'ca.crt','path':'ca.crt'}]}}]}}}}
   (folder/'central-postgres-patch.yaml').write_text(yaml.safe_dump(patch,sort_keys=False))
   k.setdefault('resources',[])
   if 'sealed-central-postgres.yaml' not in k['resources']:k['resources'].append('sealed-central-postgres.yaml')
   k.setdefault('patches',[])
   if {'path':'central-postgres-patch.yaml'} not in k['patches']:k['patches'].append({'path':'central-postgres-patch.yaml'})
  if old:
   patch={'apiVersion':'apps/v1','kind':'StatefulSet' if kind=='statefulset' else 'Deployment','metadata':{'name':old,'annotations':{'argocd.argoproj.io/sync-options':'Prune=false,Delete=false'}},'spec':{'replicas':0}}
   filename=key+'-retired-database.yaml';(folder/filename).write_text(yaml.safe_dump(patch,sort_keys=False))
   # The v1 PF workload is deliberately no longer in the current overlay; retain it explicitly elsewhere.
   if key!='pf_legacy_prod':
    k.setdefault('patches',[])
    if {'path':filename} not in k['patches']:k['patches'].append({'path':filename})
  kpath.write_text(yaml.safe_dump(k,sort_keys=False))
  log('app_configuration_prepared',database=key)
def pause_gitops(ns):
 path=PRIVATE/'gitops-state.json';saved=json.loads(path.read_text()) if path.exists() else {}
 for name in ['root-apps',ns]:
  if name not in saved:
   app=get('application',name,'argocd');saved[name]=app['spec'].get('syncPolicy',{}).get('automated');path.write_text(json.dumps(saved))
  oc('patch','application',name,'-n','argocd','--type=merge','-p',json.dumps({'spec':{'syncPolicy':{'automated':{'enabled':False}}}}))
 log('gitops_paused',application=ns)
def dump_source(key,phase):
 m=MAP[key];pod=source_pod(m);db=m[4];ns=m[0]
 path=PRIVATE/(key+'-'+phase+'.dump')
 with open(path,'wb') as f:
  run(['oc','exec','-n',ns,pod,'--','env','PGOPTIONS=-c default_transaction_read_only=on','pg_dump','-U','postgres','-d',db,'--format=custom'],stdout=f)
 with open(path,'rb') as f:run(['docker','run','--rm','-i','--entrypoint','pg_restore','postgres:16.15-bookworm','--list'],stdin=f)
 digest=hashlib.sha256(path.read_bytes()).hexdigest();path.with_suffix('.dump.sha256').write_text(digest+'  '+path.name+'\n')
 with open(PRIVATE/(key+'-'+phase+'-globals.sql'),'wb') as f:
  run(['oc','exec','-n',ns,pod,'--','pg_dumpall','-U','postgres','--globals-only','--no-role-passwords'],stdout=f)
 info=metadata(ns,pod,db);(PRIVATE/(key+'-'+phase+'.json')).write_text(json.dumps(info))
 recipient=next(l.split(': ',1)[1] for l in (PRIVATE/'backup-age-identity.txt').read_text().splitlines() if l.startswith('# public key: '))
 encrypted=path.with_suffix('.dump.age')
 with open(path,'rb') as f,open(encrypted,'wb') as out:
  run(['docker','run','--rm','-i','--entrypoint','age','ghcr.io/robbertvdzon/postgresql-platform:consolidation-20260915','-r',recipient],stdin=f,stdout=out)
 destination='/shares/external/postgres-backups/central/migration-'+encrypted.name
 with open(encrypted,'rb') as f:
  run(['oc','exec','-i','-n','smb-timemachine','deployment/samba-timemachine','--','sh','-c','cat > "$1"','sh',destination],stdin=f)
 log('source_backup_verified',database=key,phase=phase,bytes=path.stat().st_size)
 return path,info
def restore(key,path,info,probe=False):
 m=MAP[key];ns='postgres-'+m[7];db='migrationcheck_'+key if probe else key;pod='postgres-0';q=ident(db)
 if probe:
  sql(ns,pod,'postgres',f'CREATE ROLE {q} NOLOGIN; CREATE DATABASE {q} OWNER {q} TEMPLATE template0; REVOKE ALL ON DATABASE {q} FROM PUBLIC;')
 else:
  tables=int(sql(ns,pod,db,"SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');"))
  if tables:raise RuntimeError('target is not empty: '+db)
  if key=='sf_prod':sql(ns,pod,db,'DROP SCHEMA IF EXISTS software_factory;')
 with open(path,'rb') as f:
  run(['oc','exec','-i','-n',ns,pod,'--','pg_restore','-U','postgres','--role',db,'-d',db,'--no-owner','--no-acl','--exit-on-error','--single-transaction'],stdin=f)
 actual=metadata(ns,pod,db)
 if actual['flyway']!=info['flyway']:raise RuntimeError('Flyway history differs: '+db)
 if not probe and actual!=info:raise RuntimeError('counts or sequences differ: '+db)
 sql(ns,pod,db,'ANALYZE; REVOKE CREATE ON SCHEMA public FROM PUBLIC;')
 sql(ns,pod,'postgres',f'REVOKE ALL ON DATABASE {q} FROM PUBLIC;')
 if probe:sql(ns,pod,'postgres',f'DROP DATABASE {q}; DROP ROLE {q};')
 log('restore_verified',database=key,probe=probe,tables=len(actual['counts']),migrations=len(actual['flyway']))
def migrate(key):
 m=MAP[key];ns,repo,overlay,backend,db,kind,old,tier,*_=m
 pause_gitops(ns)
 if backend:
  dep=get('deployment',backend,ns);(PRIVATE/(key+'-previous-deployment.json')).write_text(json.dumps(dep))
  oc('scale','deployment/'+backend,'-n',ns,'--replicas=0')
  for _ in range(90):
   selector=','.join(k+'='+v for k,v in dep['spec']['selector']['matchLabels'].items())
   pods=json.loads(oc('get','pods','-n',ns,'-l',selector,'-o','json'))['items']
   if not pods:break
   time.sleep(2)
  else:raise RuntimeError('backend did not stop')
 if db:
  pod=source_pod(m)
  clients=int(sql(ns,pod,db,"SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid();"))
  if clients:raise RuntimeError('source still has client connections')
  path,info=dump_source(key,'final');restore(key,path,info)
 log('migration_data_ready',database=key)
def start(key):
 m=MAP[key];ns,repo,overlay,backend,db,kind,old,tier,*_=m
 if db:
  expected=json.loads((PRIVATE/(key+'-final.json')).read_text())
  if metadata('postgres-'+tier,'postgres-0',key)!=expected:raise RuntimeError('refusing switch: final restore is not verified')
 elif not (PRIVATE/(key+'-previous-deployment.json')).exists():raise RuntimeError('acceptance backend was not stopped')
 if backend:
  secret=json.loads((PRIVATE/(key+'-secret.json')).read_text())
  if secret['metadata']['name']=='central-postgres':
   secret['metadata'].setdefault('annotations',{})['sealedsecrets.bitnami.com/managed']='true'
  run(['oc','apply','-f','-'],data=json.dumps(secret).encode())
  patch=yaml.safe_load((WORK/repo/overlay/'central-postgres-patch.yaml').read_text())
  oc('patch','deployment',backend,'-n',ns,'--type=strategic','-p',json.dumps(patch))
  oc('scale','deployment/'+backend,'-n',ns,'--replicas=1')
  log('backend_start_requested',database=key)
 if old:
  oc('annotate',kind,old,'-n',ns,'argocd.argoproj.io/sync-options=Prune=false,Delete=false','--overwrite')
  oc('scale',kind+'/'+old,'-n',ns,'--replicas=0')
 log('source_retired_preserved',database=key)
def resume_gitops():
 saved=json.loads((PRIVATE/'gitops-state.json').read_text())
 for name,policy in sorted(saved.items(),key=lambda x:x[0]=='root-apps'):
  # Delete the temporary enabled override first, then restore original value.
  app=get('application',name,'argocd')
  current=app['spec'].get('syncPolicy',{}).get('automated',{})
  if 'enabled' in current:oc('patch','application',name,'-n','argocd','--type=json','-p','[{"op":"remove","path":"/spec/syncPolicy/automated/enabled"}]')
  oc('patch','application',name,'-n','argocd','--type=merge','-p',json.dumps({'spec':{'syncPolicy':{'automated':policy}}}))
 log('gitops_restored')
if __name__=='__main__':
 try:
  command=sys.argv[1]
  if command=='prepare':prepare()
  elif command=='resume-gitops':resume_gitops()
  elif command=='probe':
   k=sys.argv[2];p,i=dump_source(k,'probe');restore(k,p,i,True)
  elif command=='migrate':migrate(sys.argv[2])
  elif command=='start':start(sys.argv[2])
  else:raise ValueError('unknown command')
 except Exception as exc:
  log('migration_failed',error=str(exc));sys.exit(1)
