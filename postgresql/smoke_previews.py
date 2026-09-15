#!/usr/bin/env python3
"""Temporary nonproduction deployments to validate current preview overlays."""
import json,yaml
import migrate as m

for repo,namespace in [('personal-news-feed-by-claude-code','pnf-pr-2147483001'),('product-factory','product-factory-pr-2147483002')]:
 ns={'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace,'labels':{'argocd.argoproj.io/managed-by':'argocd','preview.vdzonsoftware.nl/managed-by':'preview-reconciler','postgres.vdzonsoftware.nl/smoke-test':'true'}}}
 m.run(['oc','apply','-f','-'],data=json.dumps(ns).encode())
 docs=list(yaml.safe_load_all(m.oc('kustomize',str(m.WORK/repo/'deploy/overlays/preview'))))
 for doc in docs:
  if not doc:continue
  if doc['kind'] in ['PersistentVolumeClaim','StatefulSet']:raise RuntimeError('Unexpected stateful preview resource')
  doc['metadata']['namespace']=namespace
  if doc['kind']=='Route':doc['spec']['host']=namespace+'-'+doc['metadata']['name']+'.vdzonsoftware.nl'
  if doc['kind']=='Deployment':
   for c in doc['spec']['template']['spec']['containers']:
    if repo=='product-factory' and c['name']=='backend':
     c.setdefault('env',[]).extend([{'name':'PF_PUBLIC_FRONTEND_URL','value':'https://'+namespace+'-dashboard-frontend.vdzonsoftware.nl'},{'name':'PF_PUBLIC_BACKEND_URL','value':'https://'+namespace+'-dashboard-backend.vdzonsoftware.nl'}])
 m.run(['oc','apply','-f','-'],data=yaml.safe_dump_all(docs,sort_keys=False).encode())
 print('Smoke preview deployed:',namespace,flush=True)
