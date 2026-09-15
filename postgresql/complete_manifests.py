#!/usr/bin/env python3
"""Generate base and operational manifests. See bootstrap.py for secret handling."""
import bootstrap as b
import json,os,re
from pathlib import Path
import yaml
identity=b.PRIVATE/'backup-age-identity.txt'
if not identity.exists():
 identity.write_bytes(b.cmd(['docker','run','--rm','--entrypoint','age-keygen','ghcr.io/robbertvdzon/postgresql-platform:consolidation-20260915']))
 identity.chmod(0o600)
recipient=next(l.split(': ',1)[1] for l in identity.read_text().splitlines() if l.startswith('# public key: '))
ns='postgres-production';folder=b.ROOT/'manifests/postgresql/production'
b.sealed('postgres-backup-encryption',ns,{'identity':identity.read_text(),'recipient':recipient},folder/'sealed-backup-encryption.yaml')
def hdd(pod,readonly=False):
 pod['securityContext'].update({'runAsUser':1000,'seLinuxOptions':{'type':'spc_t'}})
 pod['volumes'].append({'name':'backups','hostPath':{'path':'/var/mnt/external-hdd/postgres-backups/central','type':'Directory'}})
 pod['containers'][0]['volumeMounts'].append({'name':'backups','mountPath':'/backups','readOnly':readonly})
 return pod
ops=[]
for mode,schedule in [('backup','15 2 * * *'),('restorecheck','30 3 * * 0')]:
 pod=hdd(b.base_pod(ns,mode,mode=='restorecheck'))
 pod['volumes'].append({'name':'encryption','secret':{'secretName':'postgres-backup-encryption','items':[{'key':'identity' if mode=='restorecheck' else 'recipient','path':'identity' if mode=='restorecheck' else 'recipient'}]}})
 pod['containers'][0]['volumeMounts'].append({'name':'encryption','mountPath':'/encryption','readOnly':True})
 ops.append(b.resource('CronJob','postgres-'+mode,ns,api='batch/v1',spec={'schedule':schedule,'timeZone':'Europe/Amsterdam','concurrencyPolicy':'Forbid','startingDeadlineSeconds':3600,'successfulJobsHistoryLimit':2,'failedJobsHistoryLimit':3,
   'jobTemplate':{'spec':{'backoffLimit':1,'activeDeadlineSeconds':7200,'template':{'metadata':{'labels':{'postgres.vdzonsoftware.nl/operator':'true'}},'spec':pod}}}}))
b.write(folder/'operations.yaml',ops)
for tier in ['production','nonproduction']:
 ns='postgres-'+tier;folder=b.ROOT/'manifests/postgresql'/tier;ops=[]
 pod=b.base_pod(ns,'metrics');pod['restartPolicy']='Always'
 if tier=='production':hdd(pod,True)
 for e in pod['containers'][0]['env']:
  if e['name']=='PGUSER':e['value']='platform_monitor'
  if e['name']=='PGPASSWORD':e['valueFrom']['secretKeyRef']['key']='platform_monitor'
 pod['containers'][0].update({'ports':[{'name':'metrics','containerPort':9187}],'readinessProbe':{'httpGet':{'path':'/healthz','port':9187},'periodSeconds':10}})
 labels={'app':'postgres-metrics','postgres.vdzonsoftware.nl/operator':'true'}
 ops.append(b.resource('Deployment','postgres-metrics',ns,api='apps/v1',spec={'replicas':1,'selector':{'matchLabels':{'app':'postgres-metrics'}},'template':{'metadata':{'labels':labels},'spec':pod}}))
 svc=b.resource('Service','postgres-metrics',ns,spec={'selector':{'app':'postgres-metrics'},'ports':[{'name':'metrics','port':9187,'targetPort':9187}]});svc['metadata']['labels']={'app':'postgres-metrics'};ops.append(svc)
 ops.append(b.resource('NetworkPolicy','metrics-ingress',ns,api='networking.k8s.io/v1',spec={'podSelector':{'matchLabels':{'app':'postgres-metrics'}},'policyTypes':['Ingress'],'ingress':[{'from':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'openshift-monitoring'}}}],'ports':[{'protocol':'TCP','port':9187}]}]}))
 ops.append(b.resource('ServiceMonitor','central-postgres',ns,api='monitoring.coreos.com/v1',spec={'selector':{'matchLabels':{'app':'postgres-metrics'}},'endpoints':[{'port':'metrics','interval':'60s','scrapeTimeout':'20s'}]}))
 rules=[{'alert':'CentralPostgresUnavailable','expr':f'central_postgres_up{{namespace="{ns}"}} == 0','for':'2m','labels':{'severity':'critical'},'annotations':{'summary':'Centrale PostgreSQL niet bereikbaar ('+tier+')'}},
 {'alert':'CentralPostgresConnectionsHigh','expr':f'central_postgres_connections{{namespace="{ns}"}} / central_postgres_max_connections{{namespace="{ns}"}} > 0.8','for':'10m','labels':{'severity':'warning'},'annotations':{'summary':'PostgreSQL verbindingen boven 80%'}},
 {'alert':'CentralPostgresMetricsMissing','expr':f'absent(up{{namespace="{ns}",service="postgres-metrics"}} == 1)','for':'5m','labels':{'severity':'critical'},'annotations':{'summary':'PostgreSQL monitoring ontbreekt'}}]
 if tier=='production':
  for kind,hours in [('backup',26),('restore',192)]:
   rules += [{'alert':'CentralPostgres'+kind.title()+'Failed','expr':f'central_postgres_{kind}_failed{{namespace="{ns}"}} > 0','for':'5m','labels':{'severity':'critical'},'annotations':{'summary':'PostgreSQL '+kind+' mislukt of ontbreekt'}},
    {'alert':'CentralPostgres'+kind.title()+'Stale','expr':f'time() - central_postgres_{kind}_last_success{{namespace="{ns}"}} > {hours*3600}','for':'5m','labels':{'severity':'critical'},'annotations':{'summary':'PostgreSQL '+kind+' is te oud'}}]
  rules.append({'alert':'CentralPostgresBackupDiskFull','expr':f'central_postgres_backup_free_bytes{{namespace="{ns}"}} / central_postgres_backup_total_bytes{{namespace="{ns}"}} < 0.1','for':'5m','labels':{'severity':'critical'},'annotations':{'summary':'Backup-HDD minder dan 10% vrij'}})
 ops.append(b.resource('PrometheusRule','central-postgres',ns,api='monitoring.coreos.com/v1',spec={'groups':[{'name':'central-postgres.rules','rules':rules}]}))
 b.write(folder/'monitoring.yaml',ops)
ns='postgres-nonproduction';folder=b.ROOT/'manifests/postgresql/nonproduction';ops=[]
pod=b.base_pod(ns,'controller',True);pod['restartPolicy']='Always';pod['automountServiceAccountToken']=True
pod['volumes'].append({'name':'controller','secret':{'secretName':'postgres-credentials','items':[{'key':'controller-master','path':'master'}]}})
pod['containers'][0]['volumeMounts'].append({'name':'controller','mountPath':'/controller','readOnly':True})
pod['containers'][0]['readinessProbe']={'exec':{'command':['python3','-c',"import json,time; s=json.load(open('/tmp/controller-status.json')); assert not s['failed'] and time.time()-s['time']<150"]},'initialDelaySeconds':15,'periodSeconds':30}
pod['containers'][0]['env'] += [{'name':'MAX_PREVIEW_DATABASES','value':'8'},{'name':'PREVIEW_DELETE_GRACE_SECONDS','value':'3600'}]
ops.append(b.resource('Deployment','postgres-preview-controller',ns,api='apps/v1',spec={'replicas':0,'selector':{'matchLabels':{'app':'postgres-preview-controller'}},'template':{'metadata':{'labels':{'app':'postgres-preview-controller','postgres.vdzonsoftware.nl/operator':'true'}},'spec':pod}}))
# Start only after the existing preview database has been imported and registered.
ops.append(b.resource('ClusterRole','postgres-preview-controller',api='rbac.authorization.k8s.io/v1',rules=[
 {'apiGroups':[''],'resources':['namespaces'],'verbs':['get','list']},
 {'apiGroups':[''],'resources':['secrets'],'resourceNames':['preview-postgres'],'verbs':['get','patch']},
 {'apiGroups':[''],'resources':['secrets'],'verbs':['create']},
 {'apiGroups':['apps'],'resources':['deployments'],'verbs':['get','list']}]))
ops.append(b.resource('ClusterRoleBinding','postgres-preview-controller',api='rbac.authorization.k8s.io/v1',subjects=[{'kind':'ServiceAccount','name':'postgres-controller','namespace':ns}],roleRef={'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'postgres-preview-controller'}))
policy=b.resource('ValidatingAdmissionPolicy','postgres-preview-controller-boundary',api='admissionregistration.k8s.io/v1',spec={'failurePolicy':'Fail','matchConstraints':{'resourceRules':[{'apiGroups':['','apps'],'apiVersions':['v1'],'operations':['CREATE','UPDATE'],'resources':['secrets','deployments']}]},
 'matchConditions':[{'name':'controller-identity','expression':"request.userInfo.username == 'system:serviceaccount:postgres-nonproduction:postgres-controller'"}],
 'validations':[{'expression':"request.namespace.matches('^(hkh-autopilot|hkh|product-factory|pvdd|pnf)-pr-[1-9][0-9]*$')",'message':'Preview controller may write only approved PR namespaces'},
 {'expression':"request.resource.resource != 'secrets' || object.metadata.name == 'preview-postgres'",'message':'Only preview-postgres may be written'},
 {'expression':"request.resource.resource != 'deployments' || object.metadata.name in ['backend','runtime','product-factory-backend']",'message':'Only approved preview backends may be changed'}]})
ops.append(policy)
ops.append(b.resource('ValidatingAdmissionPolicyBinding','postgres-preview-controller-boundary',api='admissionregistration.k8s.io/v1',spec={'policyName':'postgres-preview-controller-boundary','validationActions':['Deny']}))
b.write(folder/'controller.yaml',ops)
for tier in ['production','nonproduction']:
 folder=b.ROOT/'manifests/postgresql'/tier
 k=yaml.safe_load((folder/'kustomization.yaml').read_text())
 k['resources'] += ['monitoring.yaml'] + (['operations.yaml','sealed-backup-encryption.yaml'] if tier=='production' else ['controller.yaml'])
 b.write(folder/'kustomization.yaml',[k])
print('Generated backup/restore, monitoring, and constrained preview-controller resources.')
