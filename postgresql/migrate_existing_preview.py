#!/usr/bin/env python3
"""One-time import of the retained PR-63 database, before enabling the controller."""
import base64, importlib.util, json
from pathlib import Path
import yaml
import migrate as m

spec=importlib.util.spec_from_file_location('platform_db',Path(__file__).parent/'scripts/platform.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
ns='product-factory-pr-63';target='postgres-nonproduction'
uid=m.get('namespace',ns,ns)['metadata']['uid']
_,db=p.preview_identity(ns,uid)
password=p.preview_password(m.STATE['nonproduction']['controller-master'],uid)
p.sql=lambda statement,database='postgres',env=None:m.sql(target,'postgres-0',database,statement)
p.provision_database(db,password)
m.MAP[db]=(ns,'product-factory-pr63','deploy/overlays/preview','runtime','productfactory','deployment','postgres','nonproduction','PF_DB_URL','PF_DB_USERNAME','PF_DB_PASSWORD')
original_pause=m.pause_gitops
m.pause_gitops=lambda _:original_pause('product-factory-preview-63')
data={k:base64.b64encode(v.encode()).decode() for k,v in {'username':db,'password':password,'ca.crt':(m.PRIVATE/'nonproduction.crt').read_text(),'url':f'jdbc:postgresql://postgres.{target}.svc:5432/{db}?sslmode=verify-full&sslrootcert=/etc/postgres-ca/ca.crt'}.items()}
secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'preview-postgres','namespace':ns},'type':'Opaque','data':data}
(m.PRIVATE/(db+'-secret.json')).write_text(json.dumps(secret))
appset=yaml.safe_load((m.ROOT/'manifests/root-app/apps/product-factory-applicationset.yaml').read_text())
patch=next(x['patch'] for x in appset['spec']['template']['spec']['source']['kustomize']['patches'] if 'preview-postgres' in x['patch'] and 'name: runtime' in x['patch'])
(m.WORK/'product-factory-pr63/deploy/overlays/preview/central-postgres-patch.yaml').write_text(patch)
m.migrate(db)
m.start(db)
p.sql('CREATE TABLE IF NOT EXISTS public.preview_registry (uid text PRIMARY KEY, namespace text NOT NULL, database_name text UNIQUE NOT NULL, missing_since timestamptz);')
p.sql(f'INSERT INTO public.preview_registry(uid,namespace,database_name) VALUES ({p.literal(uid)},{p.literal(ns)},{p.literal(db)}) ON CONFLICT (uid) DO NOTHING;')
m.log('existing_preview_imported',database=db,namespace=ns)
