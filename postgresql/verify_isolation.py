#!/usr/bin/env python3
"""Read-only production ACL checks and a disposable nonproduction connection test."""
import json
import migrate as m
for tier in ['production','nonproduction']:
 ns='postgres-'+tier
 query="""BEGIN READ ONLY;
 SELECT count(*) FROM pg_database d CROSS JOIN pg_roles r
 WHERE NOT d.datistemplate AND d.datname <> 'postgres'
 AND r.rolcanlogin AND r.rolname NOT IN ('postgres','platform_backup','platform_monitor')
 AND r.rolname <> d.datname AND has_database_privilege(r.oid,d.oid,'CONNECT');
 COMMIT;"""
 assert m.sql(ns,'postgres-0','postgres',query)=='0','Cross-application CONNECT privilege detected'
 assert m.sql(ns,'postgres-0','postgres',"BEGIN READ ONLY;SELECT count(*) FROM pg_roles WHERE rolname !~ '^pg_' AND rolname<>'postgres' AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls);COMMIT;")=='0'
 print('Database role isolation verified:',tier,flush=True)

ns='pnf-pr-2147483001'
ip=m.get('service','postgres','postgres-nonproduction')['spec']['clusterIP']
code='''import os,socket,psycopg2
settings=dict(host='postgres.postgres-nonproduction.svc',port=5432,dbname=os.environ['DB'],user=os.environ['DB'],password=os.environ['PASSWORD'],sslmode='verify-full',sslrootcert='/ca/ca.crt',connect_timeout=3)
with psycopg2.connect(**settings) as c:
 c.set_session(readonly=True)
 with c.cursor() as q:q.execute('SELECT 1');assert q.fetchone()[0]==1
print('own_database_tls_ok',flush=True)
for change in [dict(dbname='hkh_acc'),dict(sslmode='disable'),dict(host='IP')]:
 try:
  c=psycopg2.connect(**(settings|change));c.close()
 except psycopg2.OperationalError:print('forbidden_connection_rejected',flush=True)
 else:raise RuntimeError('forbidden database connection succeeded')
try:
 c=socket.create_connection(('postgres.postgres-production.svc',5432),timeout=3);c.close()
except (TimeoutError,OSError):print('production_network_blocked',flush=True)
else:raise RuntimeError('preview can reach production PostgreSQL')
'''.replace('IP',ip)
job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'postgres-isolation-check','namespace':ns},'spec':{'backoffLimit':0,'activeDeadlineSeconds':120,'template':{'metadata':{'labels':{'postgres.vdzonsoftware.nl/client':'true'}},'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'check','image':'ghcr.io/robbertvdzon/postgresql-platform@sha256:b5cd0eb9b8e866bec208dcc83b36eeddd6fb46898e490bb0e04651124607c6af','command':['python3','-c',code],'env':[{'name':name,'valueFrom':{'secretKeyRef':{'name':'preview-postgres','key':key}}} for name,key in [('DB','username'),('PASSWORD','password')]],'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'cpu':'200m','memory':'128Mi'}},'volumeMounts':[{'name':'ca','mountPath':'/ca','readOnly':True}]}],'volumes':[{'name':'ca','secret':{'secretName':'preview-postgres','items':[{'key':'ca.crt','path':'ca.crt'}]}}]}}}}
m.run(['oc','apply','-f','-'],data=json.dumps(job).encode())
print('Nonproduction connection checks started.',flush=True)
