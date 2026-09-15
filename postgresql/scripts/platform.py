#!/usr/bin/env python3
"""Trusted database provisioning, encrypted backups and disposable preview lifecycle.
No SQL, credentials, row contents or unfiltered subprocess errors enter logs.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

NAME = re.compile(r'^[a-z][a-z0-9_]{0,62}$')
PREVIEW = re.compile(r'^(hkh-autopilot|hkh|product-factory|pvdd)-pr-([1-9][0-9]*)$')
APPS = {
    'hkh': ('hkh', 'HKH_DATABASE_URL', 'HKH_DATABASE_USER', 'HKH_DATABASE_PASSWORD', ['backend']),
    'hkh-autopilot': ('hkh_autopilot', 'HKH_DATABASE_URL', 'HKH_DATABASE_USER', 'HKH_DATABASE_PASSWORD', ['backend']),
    'product-factory': ('pf', 'PF_DB_URL', 'PF_DB_USERNAME', 'PF_DB_PASSWORD', ['runtime', 'product-factory-backend']),
    'pvdd': ('pvdd', 'PVDD_DATABASE_URL', 'PVDD_DATABASE_USER', 'PVDD_DATABASE_PASSWORD', ['backend']),
}

def log(event, **fields):
    print(json.dumps({'event': event, **fields}), flush=True)

def identifier(value):
    if not NAME.fullmatch(value):
        raise ValueError('invalid SQL identifier')
    return '"' + value + '"'

def literal(value):
    return "'" + value.replace("'", "''") + "'"

def run(args, *, data=None, env=None, stdout=None, timeout=600):
    p = subprocess.run(args, input=data, stdout=stdout or subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env, timeout=timeout)
    if p.returncode:
        # PostgreSQL errors can contain data or a password literal. Never log stderr.
        raise RuntimeError(f'{Path(args[0]).name} failed (exit {p.returncode})')
    return p.stdout or b''

def sql(statement, database='postgres', env=None):
    command = ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-d', database]
    return run(command, data=statement.encode(), env=env).decode().strip()

def env_for(user=None, password=None):
    e = dict(os.environ)
    if user: e['PGUSER'] = user
    if password is not None: e['PGPASSWORD'] = password
    e['PGCONNECT_TIMEOUT'] = '10'
    return e

def registry():
    return json.loads(Path(os.environ.get('REGISTRY_FILE', '/config/registry.json')).read_text())

def fingerprint(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''): h.update(chunk)
    return h.hexdigest()

def provision_database(name, password, schema='public', readonly=False, connection_limit=10):
    q = identifier(name); sq = identifier(schema)
    found = sql('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=' + literal(name))
    if found and found != name:
        raise RuntimeError('database owner conflict: ' + name)
    if not sql('SELECT 1 FROM pg_roles WHERE rolname=' + literal(name)):
        sql(f'CREATE ROLE {q} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;')
    sql(f'ALTER ROLE {q} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT {int(connection_limit)} PASSWORD {literal(password)};')
    if not found:
        sql(f"CREATE DATABASE {q} OWNER {q} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'en_US.utf8' LC_CTYPE 'en_US.utf8';")
    sql(f'REVOKE ALL ON DATABASE {q} FROM PUBLIC; GRANT CONNECT,TEMPORARY ON DATABASE {q} TO {q};')
    sql(f'CREATE SCHEMA IF NOT EXISTS {sq} AUTHORIZATION {q}; REVOKE CREATE ON SCHEMA public FROM PUBLIC; ALTER SCHEMA {sq} OWNER TO {q};', name)
    sql(f"ALTER ROLE {q} SET idle_in_transaction_session_timeout='60s'; ALTER ROLE {q} SET lock_timeout='5s'; ALTER ROLE {q} SET statement_timeout='60s';")
    # An archive stays password-protected and cannot login through application credentials.
    if readonly:
        sql(f'ALTER ROLE {q} NOLOGIN;')

def provision():
    config = registry()
    for item in config['databases']:
        password = Path('/credentials/' + item['name']).read_text().strip()
        provision_database(item['name'], password, item.get('schema', 'public'), item.get('archive', False))
        log('database_ready', database=item['name'])
    sql('REVOKE ALL ON DATABASE postgres FROM PUBLIC; REVOKE ALL ON DATABASE template1 FROM PUBLIC;')
    backup_password = Path('/credentials/platform_backup').read_text().strip()
    if not sql("SELECT 1 FROM pg_roles WHERE rolname='platform_backup'"):
        sql('CREATE ROLE platform_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;')
    sql('ALTER ROLE platform_backup PASSWORD ' + literal(backup_password) + '; GRANT pg_read_all_data TO platform_backup; GRANT CONNECT ON DATABASE postgres TO platform_backup;')
    for item in config['databases']:
        sql(f"GRANT CONNECT ON DATABASE {identifier(item['name'])} TO platform_backup;")
    monitor_password = Path('/credentials/platform_monitor').read_text().strip()
    if not sql("SELECT 1 FROM pg_roles WHERE rolname='platform_monitor'"):
        sql('CREATE ROLE platform_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;')
    sql('ALTER ROLE platform_monitor PASSWORD ' + literal(monitor_password) + '; GRANT pg_monitor TO platform_monitor; GRANT CONNECT ON DATABASE postgres TO platform_monitor;')
    log('provisioning_complete', count=len(config['databases']))

def status_write(value):
    target = Path('/backups/status.json')
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    os.replace(tmp, target)

def verify_hdd():
    # Mount must be backed by exFAT, never a fallback directory on the SSD.
    mount = next((l.split() for l in Path('/proc/mounts').read_text().splitlines()
                  if l.split()[1] == '/backups'), None)
    if not mount or mount[2] != 'exfat':
        raise RuntimeError('external HDD mount is missing or filesystem differs')
    if shutil.disk_usage('/backups').free < 5 * 1024 ** 3:
        raise RuntimeError('external HDD has less than 5 GiB free')

def encrypt(source, target, recipient):
    temp = target.with_name('.' + target.name + '.partial')
    run(['age', '-r', recipient, '-o', str(temp), str(source)])
    with open(temp, 'rb') as stream: os.fsync(stream.fileno())
    os.replace(temp, target)
    target.with_suffix(target.suffix + '.sha256').write_text(f'{fingerprint(target)}  {target.name}\n')

def select_retained(records, now):
    """Keep all complete daily points for 30 days and weekly/monthly representatives."""
    records = sorted(records, key=lambda x: x['epoch'], reverse=True)
    keep = set(); weeks = set(); months = set()
    for item in records:
        dt = datetime.fromtimestamp(item['epoch'], timezone.utc)
        week = dt.isocalendar()[:2]; month = (dt.year, dt.month)
        wanted = now - item['epoch'] <= 30 * 86400
        if week not in weeks and len(weeks) < 8: weeks.add(week); wanted = True
        if month not in months and len(months) < 12: months.add(month); wanted = True
        if wanted: keep.add(item['run'])
    if records: keep.add(records[0]['run'])
    return keep

def backup():
    verify_hdd()
    cfg = registry(); root = Path('/backups'); root.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    recipient = Path('/encryption/recipient').read_text().strip()
    expected = {d['name'] for d in cfg['databases']}
    actual = set(sql("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname<>'postgres' AND datname NOT LIKE 'restorecheck_%' AND datname NOT LIKE 'migrationcheck_%';").splitlines())
    if expected != actual:
        raise RuntimeError('database registry differs from server catalog')
    previous = json.loads((root/'status.json').read_text()) if (root/'status.json').exists() else {}
    state = previous; state['attempt'] = time.time(); state['databases'] = state.get('databases', {})
    state['failed'] = False
    with tempfile.TemporaryDirectory(prefix='pg-backup-', dir='/scratch') as scratch:
        tmp = Path(scratch)
        globals_file = tmp/'globals.sql'
        with open(globals_file, 'wb') as stream:
            run(['pg_dumpall', '--globals-only', '--no-role-passwords'], stdout=stream)
        globals_target = root/'globals'; globals_target.mkdir(exist_ok=True)
        encrypt(globals_file, globals_target/(stamp+'.sql.age'), recipient)
        for item in cfg['databases']:
            name = item['name']; identifier(name)
            try:
                dump = tmp/(name+'.dump')
                import psycopg2
                with psycopg2.connect(dbname=name) as conn:
                    conn.set_session(isolation_level='REPEATABLE READ', readonly=True)
                    with conn.cursor() as cur:
                        cur.execute('SELECT pg_export_snapshot()')
                        snapshot = cur.fetchone()[0]
                        run(['pg_dump', '-d', name, '--snapshot', snapshot, '--format=custom', '--compress=6', '--file', str(dump)])
                        cur.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2")
                        tables = cur.fetchall(); counts = {}
                        from psycopg2 import sql as ps
                        for sc,tab in tables:
                            cur.execute(ps.SQL('SELECT count(*) FROM {}.{}').format(ps.Identifier(sc),ps.Identifier(tab)))
                            counts[sc+'.'+tab] = cur.fetchone()[0]
                        cur.execute(ps.SQL('SELECT version,type,success,checksum FROM {}.flyway_schema_history ORDER BY installed_rank').format(ps.Identifier(item.get('schema','public'))))
                        history = cur.fetchall()

                run(['pg_restore', '--list', str(dump)])
                target = root/name/stamp; target.mkdir(parents=True, exist_ok=False)
                manifest = {'database': name, 'epoch': time.time(), 'run': stamp,
                            'sha256': fingerprint(dump), 'globals': stamp+'.sql.age', 'table_counts':counts, 'flyway':history,
                            'server_version': sql('SHOW server_version;', name), 'schema': item.get('schema', 'public')}
                manifest_file = tmp/(name+'.json'); manifest_file.write_text(json.dumps(manifest))
                encrypt(dump, target/(name+'.dump.age'), recipient)
                encrypt(manifest_file, target/'metadata.json.age', recipient)
                (target/'complete.json').write_text(json.dumps({'run': stamp, 'epoch': manifest['epoch']}))
                state['databases'][name] = {'success': time.time(), 'run': stamp, 'failed': False}
                records = [json.loads(x.read_text()) for x in (root/name).glob('*/complete.json')]
                retained = select_retained(records, time.time())
                for old in records:
                    if old['run'] not in retained: shutil.rmtree(root/name/old['run'])
                dump.unlink(); manifest_file.unlink()
                log('backup_ok', database=name, run=stamp)
            except Exception as exc:
                state['failed'] = True
                state['databases'].setdefault(name, {})['failed'] = True
                log('backup_failed', database=name, error=type(exc).__name__)
            status_write(state)
        # Keep globals for every retained per-database run, plus the current run.
        used = {p.parent.name for p in root.glob('*/*/complete.json')} | {stamp}
        for p in globals_target.glob('*.sql.age'):
            if p.name.removesuffix('.sql.age') not in used:
                p.unlink(); p.with_suffix(p.suffix+'.sha256').unlink(missing_ok=True)
    if state['failed']: raise RuntimeError('one or more database backups failed')
    log('backup_complete')

def checked_decrypt(source, dest):
    expected = source.with_suffix(source.suffix+'.sha256').read_text().split()[0]
    if not hmac.compare_digest(fingerprint(source), expected): raise RuntimeError('encrypted checksum mismatch')
    run(['age', '-d', '-i', '/encryption/identity', '-o', str(dest), str(source)])

def restorecheck():
    verify_hdd(); state = {'attempt': time.time(), 'databases': {}, 'failed': False}
    for item in registry()['databases']:
        name = item['name']; check = 'restorecheck_' + name + '_' + secrets.token_hex(4)
        password = secrets.token_urlsafe(40)
        try:
            candidates = sorted(Path('/backups', name).glob('*/complete.json'))
            if not candidates: raise RuntimeError('no complete backup')
            folder = candidates[-1].parent
            with tempfile.TemporaryDirectory(prefix='pg-restore-', dir='/scratch') as scratch:
                dump = Path(scratch)/'data.dump'; metadata = Path(scratch)/'metadata.json'
                checked_decrypt(folder/(name+'.dump.age'), dump)
                checked_decrypt(folder/'metadata.json.age', metadata)
                manifest = json.loads(metadata.read_text())
                if not hmac.compare_digest(fingerprint(dump), manifest['sha256']): raise RuntimeError('dump checksum mismatch')
                run(['pg_restore', '--list', str(dump)])
                provision_database(check, password)
                e = env_for(check, password); e['PGOPTIONS'] = '-c statement_timeout=0 -c lock_timeout=0'
                run(['pg_restore', '--dbname', check, '--no-owner', '--no-acl', '--exit-on-error', '--single-transaction', str(dump)], env=e)
                for table, expected in manifest['table_counts'].items():
                    sc, tab = table.split('.',1)
                    if int(sql(f'SELECT count(*) FROM {identifier(sc)}.{identifier(tab)};',check,e)) != expected:
                        raise RuntimeError('restored table count mismatch')
                current_history = json.loads(sql(f"SELECT coalesce(json_agg(t),'[]') FROM (SELECT version,type,success,checksum FROM {identifier(item.get('schema','public'))}.flyway_schema_history ORDER BY installed_rank) t;",check,e))
                if [list(r.values()) for r in current_history] != manifest['flyway']:
                    raise RuntimeError('restored Flyway history mismatch')
                schema = identifier(item.get('schema', 'public'))
                failed = sql(f'SELECT count(*) FROM {schema}.flyway_schema_history WHERE NOT success;', check, e)
                if failed != '0': raise RuntimeError('failed Flyway migration in restored database')
                invalid = sql("SELECT count(*) FROM pg_index WHERE NOT indisvalid;", check, e)
                if invalid != '0': raise RuntimeError('invalid restored index')
                if sql(f"SELECT count(*) FROM pg_roles WHERE rolcanlogin AND rolname NOT IN ('postgres','platform_backup',{literal(check)}) AND has_database_privilege(oid,{literal(check)},'CONNECT');") != '0':
                    raise RuntimeError('restored database is accessible to another app')
                state['databases'][name] = {'success': time.time(), 'run': folder.name}
                log('restore_ok', database=name, run=folder.name)
        except Exception as exc:
            state['failed'] = True; state['databases'][name] = {'failed': True}
            log('restore_failed', database=name, error=type(exc).__name__)
        finally:
            sql(f'DROP DATABASE IF EXISTS {identifier(check)} WITH (FORCE); DROP ROLE IF EXISTS {identifier(check)};')
    target = Path('/backups/restore-status.json'); temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(state)); os.replace(temporary, target)
    if state['failed']: raise RuntimeError('one or more restore checks failed')

class Kube:
    def __init__(self):
        base = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.token = (base/'token').read_text().strip()
        self.context = ssl.create_default_context(cafile=str(base/'ca.crt'))
        self.url = 'https://kubernetes.default.svc'
    def request(self, method, path, data=None):
        raw = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(self.url+path, raw, method=method,
            headers={'Authorization': 'Bearer '+self.token, 'Content-Type': 'application/merge-patch+json' if method=='PATCH' else 'application/json'})
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=20) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in [404,409]: return {'http_error': e.code}
            raise RuntimeError('Kubernetes request failed: '+str(e.code)) from None

def preview_identity(namespace, uid):
    match = PREVIEW.fullmatch(namespace)
    if not match or not re.fullmatch(r'[a-f0-9-]{36}', uid): raise ValueError('invalid preview identity')
    app, pr = match.groups()
    db = f'{APPS[app][0]}_pr_{pr}_{hashlib.sha256(uid.encode()).hexdigest()[:8]}'
    identifier(db)
    return app, db

def preview_password(master, uid):
    return hmac.new(master.encode(), uid.encode(), hashlib.sha256).hexdigest()

def preview_cycle(kube):
    # Registry and passwords live only in the nonproduction control plane.
    namespaces = kube.request('GET', '/api/v1/namespaces')['items']
    alive = {n['metadata']['uid']: n for n in namespaces if PREVIEW.fullmatch(n['metadata']['name']) and not n['metadata'].get('deletionTimestamp')}
    sql('CREATE TABLE IF NOT EXISTS public.preview_registry (uid text PRIMARY KEY, namespace text NOT NULL, database_name text UNIQUE NOT NULL, missing_since timestamptz);')
    registered = json.loads(sql("SELECT coalesce(json_agg(t),'[]') FROM (SELECT uid,namespace,database_name,extract(epoch FROM missing_since) missing_since FROM public.preview_registry) t;"))
    master = Path('/controller/master').read_text().strip()
    for uid, nsobj in alive.items():
        ns = nsobj['metadata']['name']; app, db = preview_identity(ns, uid)
        entry = next((r for r in registered if r['uid']==uid), None)
        if not entry and len(registered) >= int(os.environ.get('MAX_PREVIEW_DATABASES', '8')):
            log('preview_capacity_exceeded', namespace=ns); continue
        password = preview_password(master, uid)
        if not entry:
            provision_database(db, password)
            sql(f'INSERT INTO public.preview_registry(uid,namespace,database_name) VALUES ({literal(uid)},{literal(ns)},{literal(db)}) ON CONFLICT (uid) DO NOTHING;')
            registered.append({'uid': uid, 'namespace': ns, 'database_name': db, 'missing_since': None})
        else:
            sql(f'UPDATE public.preview_registry SET missing_since=NULL WHERE uid={literal(uid)} AND missing_since IS NOT NULL;')
        data = {k: base64.b64encode(v.encode()).decode() for k,v in {'username':db, 'password':password,
                'ca.crt':Path('/pgca/ca.crt').read_text(), 'url':f'jdbc:postgresql://postgres.postgres-nonproduction.svc:5432/{db}?sslmode=verify-full&sslrootcert=/etc/postgres-ca/ca.crt'}.items()}
        path = '/api/v1/namespaces/'+ns+'/secrets/preview-postgres'
        current = kube.request('GET', path)
        if current.get('data') != data:
            body = {'apiVersion':'v1','kind':'Secret','metadata':{'name':'preview-postgres','namespace':ns},'type':'Opaque','data':data}
            if current.get('http_error') == 404: kube.request('POST', '/api/v1/namespaces/'+ns+'/secrets', body)
            else: kube.request('PATCH', path, {'data':data})
        _,urlvar,uservar,passvar,names = APPS[app]
        deployments = kube.request('GET', '/apis/apps/v1/namespaces/'+ns+'/deployments')['items']
        for dep in deployments:
            if dep['metadata']['name'] not in names: continue
            template = dep['spec']['template']; marker = template['metadata'].get('annotations',{}).get('postgres.vdzonsoftware.nl/database')
            if marker == db: continue
            containers = template['spec']['containers']
            for c in containers:
                env = [e for e in c.get('env',[]) if e['name'] not in [urlvar,uservar,passvar,'SPRING_DATASOURCE_URL','SPRING_DATASOURCE_USERNAME','SPRING_DATASOURCE_PASSWORD','SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE','SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE']]
                for key,field in [(urlvar,'url'),(uservar,'username'),(passvar,'password'),('SPRING_DATASOURCE_URL','url'),('SPRING_DATASOURCE_USERNAME','username'),('SPRING_DATASOURCE_PASSWORD','password')]:
                    env.append({'name':key,'valueFrom':{'secretKeyRef':{'name':'preview-postgres','key':field}}})
                env += [{'name':'SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE','value':'5'}, {'name':'SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE','value':'0'}]
                c['env']=env
                c['volumeMounts'] = [m for m in c.get('volumeMounts',[]) if m['name']!='central-postgres-ca'] + [{'name':'central-postgres-ca','mountPath':'/etc/postgres-ca','readOnly':True}]
            kube.request('PATCH','/apis/apps/v1/namespaces/'+ns+'/deployments/'+dep['metadata']['name'],
                {'spec':{'template':{'metadata':{'annotations':{'postgres.vdzonsoftware.nl/database':db}, 'labels':{'postgres.vdzonsoftware.nl/client':'true'}},'spec':{'containers':containers, 'volumes':[v for v in template['spec'].get('volumes',[]) if v['name']!='central-postgres-ca'] + [{'name':'central-postgres-ca','secret':{'secretName':'preview-postgres','items':[{'key':'ca.crt','path':'ca.crt'}]}}]}}}})
        log('preview_ready', namespace=ns, database=db)
    for entry in registered:
        if entry['uid'] in alive: continue
        # A replacement namespace never authorizes deleting its database; match the stored UID/name.
        app, expected = preview_identity(entry['namespace'], entry['uid'])
        if entry['database_name'] != expected: raise RuntimeError('preview registry ownership mismatch')
        if entry['missing_since'] is None:
            sql(f'UPDATE public.preview_registry SET missing_since=now() WHERE uid={literal(entry["uid"])};')
        elif time.time()-float(entry['missing_since']) >= int(os.environ.get('PREVIEW_DELETE_GRACE_SECONDS','3600')):
            sql(f'DROP DATABASE IF EXISTS {identifier(expected)} WITH (FORCE); DROP ROLE IF EXISTS {identifier(expected)};')
            sql(f'DELETE FROM public.preview_registry WHERE uid={literal(entry["uid"])};')
            log('preview_deleted', namespace=entry['namespace'], database=expected)

def controller():
    kube = Kube()
    while True:
        try: preview_cycle(kube)
        except Exception as exc: log('preview_reconcile_failed', error=type(exc).__name__)
        time.sleep(60)

def metrics():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == '/healthz':
                self.send_response(200); self.end_headers(); self.wfile.write(b'ok'); return
            lines=[]
            try:
                rows=json.loads(sql("SELECT coalesce(json_agg(t),'[]') FROM (SELECT datname,pg_database_size(oid) bytes FROM pg_database WHERE NOT datistemplate) t;"))
                lines.append('central_postgres_up 1')
                for r in rows:
                    if not NAME.fullmatch(r['datname']):continue
                    lines.append(f'central_postgres_database_bytes{{database="{r["datname"]}"}} {r["bytes"]}')
                lines.append('central_postgres_connections '+sql("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend';"))
                lines.append('central_postgres_max_connections '+sql('SHOW max_connections;'))
            except Exception: lines.append('central_postgres_up 0')
            for filename,prefix in [('status.json','backup'),('restore-status.json','restore')]:
                path=Path('/backups')/filename
                if path.exists():
                    state=json.loads(path.read_text())
                    lines.append(f'central_postgres_{prefix}_failed {1 if state.get("failed") else 0}')
                    for db,r in state.get('databases',{}).items():
                        if NAME.fullmatch(db): lines.append(f'central_postgres_{prefix}_last_success{{database="{db}"}} {r.get("success",0)}')
                else:lines.append(f'central_postgres_{prefix}_failed 1')
            if Path('/backups').exists():
                disk=shutil.disk_usage('/backups')
                lines += [f'central_postgres_backup_free_bytes {disk.free}', f'central_postgres_backup_total_bytes {disk.total}']
            body=('\n'.join(lines)+'\n').encode()
            self.send_response(200);self.send_header('Content-Type','text/plain');self.end_headers();self.wfile.write(body)
    HTTPServer(('0.0.0.0',9187),Handler).serve_forever()

if __name__ == '__main__':
    try:
        {'provision': provision, 'backup': backup, 'restorecheck': restorecheck, 'controller':controller, 'metrics':metrics}[sys.argv[1]]()
    except Exception as exc:
        log('operation_failed', operation=sys.argv[1] if len(sys.argv)>1 else 'missing', error=type(exc).__name__)
        sys.exit(1)
