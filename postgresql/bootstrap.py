#!/usr/bin/env python3
"""Generate strict SealedSecrets and declarative manifests; never print credentials.
Run only by an authorized human/operator, not by an Agent Runtime job.
"""
import base64,json,os,secrets,subprocess
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=Path.home()/'.local/share/postgresql-consolidation/20260915'
PRIVATE.mkdir(parents=True,exist_ok=True);PRIVATE.chmod(0o700)
os.umask(0o077)
STATE=PRIVATE/'state.json'
if not STATE.exists() and (ROOT/'manifests/postgresql/production/sealed-credentials.yaml').exists():
 raise RuntimeError('Refusing to replace deployed credentials without the original private state')
state=json.loads(STATE.read_text()) if STATE.exists() else {}
PG='docker.io/library/postgres@sha256:1938c16e9d2f10a6a3623b344b64ae8d45f407f2c5f34f0979468bb689b9227a'
PLATFORM=os.environ.get('PLATFORM_IMAGE','ghcr.io/robbertvdzon/postgresql-platform@sha256:b5cd0eb9b8e866bec208dcc83b36eeddd6fb46898e490bb0e04651124607c6af')
REGISTRY={
'production':[{'name':n,**opts} for n,opts in [('ar_prod',{}),('hkh_prod',{}),('hkh_autopilot_prod',{}),('pf_prod',{}),('pf_legacy_prod',{'archive':True}),('pvdd_prod',{}),('sf_prod',{'schema':'software_factory'})]],
'nonproduction':[{'name':n} for n in ['ar_acc','hkh_acc','hkh_autopilot_acc','pf_acc','pvdd_acc']]}
def cmd(args,**kw):
 r=subprocess.run(args,capture_output=True,**kw)
 if r.returncode:raise RuntimeError(args[0]+' failed')
 return r.stdout
cert=PRIVATE/'sealed-secrets.crt'
if not cert.exists():cert.write_bytes(cmd(['/opt/homebrew/bin/kubeseal','--fetch-cert','--controller-name=sealed-secrets-controller','--controller-namespace=kube-system']))
def resource(kind,name,ns=None,api='v1',**kwargs):
 return {'apiVersion':api,'kind':kind,'metadata':{'name':name,**({'namespace':ns} if ns else {})},**kwargs}
def write(path,docs):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(yaml.safe_dump_all(docs,sort_keys=False));path.chmod(0o644)
def sealed(name,ns,values,path):
 s=resource('Secret',name,ns,type='Opaque',data={k:base64.b64encode(v.encode()).decode() for k,v in values.items()})
 b=cmd(['/opt/homebrew/bin/kubeseal','--cert',str(cert),'--scope','strict','--format','yaml'],input=json.dumps(s).encode())
 path.write_bytes(b);path.chmod(0o644)
def secret_env(name,key,secret):return {'name':name,'valueFrom':{'secretKeyRef':{'name':secret,'key':key}}}
def base_pod(ns,operation,admin=False):
 env=[{'name':'PGHOST','value':f'postgres.{ns}.svc'},{'name':'PGPORT','value':'5432'},{'name':'PGDATABASE','value':'postgres'},
      {'name':'PGUSER','value':'postgres' if admin else 'platform_backup'},secret_env('PGPASSWORD','admin' if admin else 'platform_backup','postgres-credentials'),
      {'name':'PGSSLMODE','value':'verify-full'},{'name':'PGSSLROOTCERT','value':'/pgca/ca.crt'},{'name':'PGCONNECT_TIMEOUT','value':'10'}]
 return {'serviceAccountName':'postgres-'+operation,'automountServiceAccountToken':False,'restartPolicy':'Never',
  'securityContext':{'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},
  'containers':[{'name':operation,'image':PLATFORM,'args':[operation], 'env':env,
   'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},
   'resources':{'requests':{'cpu':'25m','memory':'64Mi'},'limits':{'cpu':'500m','memory':'512Mi'}},
   'volumeMounts':[{'name':'config','mountPath':'/config','readOnly':True},{'name':'ca','mountPath':'/pgca','readOnly':True},{'name':'scratch','mountPath':'/scratch'}]}],
  'volumes':[{'name':'config','configMap':{'name':'postgres-config'}},{'name':'ca','secret':{'secretName':'postgres-tls','items':[{'key':'ca.crt','path':'ca.crt'}]}},{'name':'scratch','emptyDir':{'sizeLimit':'4Gi'}}]}
for tier,dbs in REGISTRY.items():
 ns='postgres-'+tier;folder=ROOT/'manifests/postgresql'/tier;folder.mkdir(parents=True,exist_ok=True)
 creds=state.setdefault(tier,{})
 for key in ['admin','platform_backup','platform_monitor','controller-master']+[x['name'] for x in dbs]:creds.setdefault(key,secrets.token_urlsafe(40))
 STATE.write_text(json.dumps(state));STATE.chmod(0o600)
 key=PRIVATE/(tier+'.key');crt=PRIVATE/(tier+'.crt')
 if not crt.exists():
  cmd(['openssl','req','-x509','-newkey','rsa:3072','-nodes','-days','3650','-subj','/CN=postgres.'+ns+'.svc',
       '-addext','subjectAltName=DNS:postgres.'+ns+'.svc,DNS:postgres.'+ns+'.svc.cluster.local',
       '-addext','basicConstraints=critical,CA:TRUE','-keyout',str(key),'-out',str(crt)])
 sealed('postgres-credentials',ns,creds,folder/'sealed-credentials.yaml')
 sealed('postgres-tls',ns,{'tls.key':key.read_text(),'tls.crt':crt.read_text(),'ca.crt':crt.read_text()},folder/'sealed-tls.yaml')
 prod=tier=='production';mem='1536Mi' if prod else '768Mi';req='768Mi' if prod else '384Mi'
 docs=[]
 namespace=resource('Namespace',ns);namespace['metadata']['labels']={'argocd.argoproj.io/managed-by':'argocd','postgres.vdzonsoftware.nl/tier':tier,'openshift.io/cluster-monitoring':'true'}
 namespace['metadata']['annotations']={'argocd.argoproj.io/sync-options':'Prune=false,Delete=false'};docs.append(namespace)
 pvc=resource('PersistentVolumeClaim','postgres-data',ns,spec={'accessModes':['ReadWriteOnce'],'storageClassName':'local-path','resources':{'requests':{'storage':'20Gi' if prod else '10Gi'}}})
 pvc['metadata']['annotations']={'argocd.argoproj.io/sync-options':'Prune=false,Delete=false'};docs.append(pvc)
 for op in ['server','provision','backup','restorecheck','metrics','controller']:
  docs.append(resource('ServiceAccount','postgres-'+op,ns,automountServiceAccountToken=False))
  scc='postgresql-host-backup' if op in ['backup','restorecheck','metrics'] and prod else 'local-path-postgresql'
  docs.append(resource('RoleBinding','postgres-'+op+'-scc',ns,api='rbac.authorization.k8s.io/v1',subjects=[{'kind':'ServiceAccount','name':'postgres-'+op,'namespace':ns}],roleRef={'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'system:openshift:scc:'+scc}))
 conf="\n".join(["listen_addresses='*'",'port=5432',"hba_file='/config/pg_hba.conf'",'max_connections='+('80' if prod else '100'),
  'shared_buffers='+('256MB' if prod else '128MB'),'effective_cache_size='+('1GB' if prod else '512MB'),
  'work_mem='+('4MB' if prod else '2MB'),'maintenance_work_mem='+('64MB' if prod else '32MB'),
  'autovacuum_work_mem='+('32MB' if prod else '16MB'),'max_wal_size='+('1GB' if prod else '512MB'),
  "password_encryption='scram-sha-256'","timezone='Etc/UTC'","ssl=on","ssl_cert_file='/run/postgres-tls/server.crt'","ssl_key_file='/run/postgres-tls/server.key'",
  "log_statement='none'","log_min_error_statement='panic'","log_error_verbosity='terse'"])+"\n"
 hba="""local all postgres trust
local all all reject
hostnossl all all 0.0.0.0/0 reject
hostssl all postgres 0.0.0.0/0 scram-sha-256
hostssl all platform_backup 0.0.0.0/0 scram-sha-256
hostssl postgres platform_monitor 0.0.0.0/0 scram-sha-256
hostssl sameuser all 0.0.0.0/0 scram-sha-256
host all all 0.0.0.0/0 reject
"""
 docs.append(resource('ConfigMap','postgres-config',ns,data={'postgresql.conf':conf,'pg_hba.conf':hba,'registry.json':json.dumps({'databases':dbs},indent=2)}))
 for name,headless in [('postgres',False),('postgres-headless',True)]:
  docs.append(resource('Service',name,ns,spec={'selector':{'app':'central-postgres'},'ports':[{'name':'postgres','port':5432,'targetPort':5432}],**({'clusterIP':'None'} if headless else {})}))
 pod={'serviceAccountName':'postgres-server','automountServiceAccountToken':False,'terminationGracePeriodSeconds':120,
  'securityContext':{'runAsNonRoot':True,'seLinuxOptions':{'type':'spc_t'},'seccompProfile':{'type':'RuntimeDefault'}},
  'initContainers':[{'name':'tls-permissions','image':PG,'command':['sh','-ec','cp /tls/tls.crt /run/postgres-tls/server.crt; cp /tls/tls.key /run/postgres-tls/server.key; chmod 600 /run/postgres-tls/server.key'],
   'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},'volumeMounts':[{'name':'tls','mountPath':'/tls','readOnly':True},{'name':'tls-private','mountPath':'/run/postgres-tls'}]}],
  'containers':[{'name':'postgres','image':PG,'args':['postgres','-c','config_file=/config/postgresql.conf'],
   'env':[{'name':'PGDATA','value':'/var/lib/postgresql/data/pgdata'},{'name':'POSTGRES_USER','value':'postgres'},secret_env('POSTGRES_PASSWORD','admin','postgres-credentials'),{'name':'POSTGRES_INITDB_ARGS','value':'--encoding=UTF8 --locale=en_US.utf8 --auth-host=scram-sha-256 --auth-local=trust'}],
   'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},'ports':[{'containerPort':5432,'name':'postgres'}],
   'resources':{'requests':{'cpu':'500m' if prod else '100m','memory':req},'limits':{'cpu':'2' if prod else '1','memory':mem}},
   'startupProbe':{'exec':{'command':['pg_isready','-h','127.0.0.1','-U','postgres','-d','postgres']},'periodSeconds':5,'failureThreshold':60},
   'readinessProbe':{'exec':{'command':['pg_isready','-h','127.0.0.1','-U','postgres','-d','postgres']},'periodSeconds':5},
   'livenessProbe':{'exec':{'command':['pg_isready','-h','127.0.0.1','-U','postgres','-d','postgres']},'periodSeconds':20,'failureThreshold':6},
   'volumeMounts':[{'name':'data','mountPath':'/var/lib/postgresql/data'},{'name':'config','mountPath':'/config','readOnly':True},{'name':'tls-private','mountPath':'/run/postgres-tls'},{'name':'dshm','mountPath':'/dev/shm'}]}],
  'volumes':[{'name':'data','persistentVolumeClaim':{'claimName':'postgres-data'}},{'name':'config','configMap':{'name':'postgres-config'}},{'name':'tls','secret':{'secretName':'postgres-tls'}},{'name':'tls-private','emptyDir':{'medium':'Memory','sizeLimit':'1Mi'}},{'name':'dshm','emptyDir':{'medium':'Memory','sizeLimit':'128Mi'}}]}
 docs.append(resource('StatefulSet','postgres',ns,api='apps/v1',spec={'serviceName':'postgres-headless','replicas':1,'updateStrategy':{'type':'OnDelete'},'selector':{'matchLabels':{'app':'central-postgres'}},'template':{'metadata':{'labels':{'app':'central-postgres'}},'spec':pod}}))
 provision=base_pod(ns,'provision',True);provision['containers'][0]['volumeMounts'].append({'name':'credentials','mountPath':'/credentials','readOnly':True});provision['volumes'].append({'name':'credentials','secret':{'secretName':'postgres-credentials'}})
 job=resource('Job','postgres-provision',ns,api='batch/v1',spec={'backoffLimit':3,'activeDeadlineSeconds':600,'template':{'metadata':{'labels':{'postgres.vdzonsoftware.nl/operator':'true'}},'spec':provision}})
 job['metadata']['annotations']={'argocd.argoproj.io/hook':'Sync','argocd.argoproj.io/sync-wave':'1','argocd.argoproj.io/hook-delete-policy':'BeforeHookCreation,HookSucceeded'};docs.append(job)
 # Default deny, explicit backend access, and operator/monitor networking.
 docs.append(resource('NetworkPolicy','default-deny',ns,api='networking.k8s.io/v1',spec={'podSelector':{},'policyTypes':['Ingress','Egress']}))
 clients=['agent-runtime','hkh','hkh-autopilot','product-factory','pvdd','software-factory'] if prod else ['agent-runtime-acceptance','hkh-acceptance','hkh-autopilot-acceptance','product-factory-acceptance','pvdd-acceptance']
 peers=[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':n}},'podSelector':{'matchLabels':{'postgres.vdzonsoftware.nl/client':'true'}}} for n in clients]
 if not prod:peers.append({'namespaceSelector':{'matchLabels':{'preview.vdzonsoftware.nl/managed-by':'preview-reconciler'}},'podSelector':{'matchLabels':{'postgres.vdzonsoftware.nl/client':'true'}}})
 peers.append({'podSelector':{'matchLabels':{'postgres.vdzonsoftware.nl/operator':'true'}}})
 docs.append(resource('NetworkPolicy','postgres-ingress',ns,api='networking.k8s.io/v1',spec={'podSelector':{'matchLabels':{'app':'central-postgres'}},'policyTypes':['Ingress'],'ingress':[{'from':peers,'ports':[{'protocol':'TCP','port':5432}]}]}))
 docs.append(resource('NetworkPolicy','operator-egress',ns,api='networking.k8s.io/v1',spec={'podSelector':{'matchLabels':{'postgres.vdzonsoftware.nl/operator':'true'}},'policyTypes':['Egress'],'egress':[{'to':[{'podSelector':{'matchLabels':{'app':'central-postgres'}}}],'ports':[{'protocol':'TCP','port':5432}]},{'ports':[{'protocol':'UDP','port':53},{'protocol':'TCP','port':53},{'protocol':'UDP','port':5353},{'protocol':'TCP','port':5353}]},{'ports':[{'protocol':'TCP','port':443},{'protocol':'TCP','port':6443}]}]}))
 write(folder/'resources.yaml',docs)
 write(folder/'kustomization.yaml',[{'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','resources':['resources.yaml','sealed-credentials.yaml','sealed-tls.yaml']}])
 app=resource('Application','postgres-'+tier,'argocd',api='argoproj.io/v1alpha1',spec={'project':'postgresql-platform','source':{'repoURL':'https://github.com/robbertvdzon/robberts-infrastructure.git','targetRevision':'main','path':'manifests/postgresql/'+tier},'destination':{'server':'https://kubernetes.default.svc','namespace':ns},'syncPolicy':{'automated':{'prune':False,'selfHeal':True},'syncOptions':['CreateNamespace=true']}})
 write(ROOT/'manifests/root-app/apps'/('postgres-'+tier+'-application.yaml'),[app])
print('Generated two isolated PostgreSQL manifests and strict SealedSecrets; credentials were not printed.')
