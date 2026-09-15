#!/usr/bin/env python3
"""Kopieert uitsluitend de agent-logincredential naar het macOS-klembord, nooit naar stdout."""
import argparse
import base64
import json
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('namespace', choices=['hkh', 'hkh-autopilot', 'pvdd', 'software-factory', 'personal-news-feed', 'robberts-assistent'])
parser.add_argument('--production-approved-for-this-task', action='store_true', help='Alleen gebruiken na expliciete toestemming van Robbert in de huidige taak')
args = parser.parse_args()
if not args.production_approved_for_this_task:
    parser.error('Productielogin vereist expliciete toestemming voor deze taak. Onderzoek standaard via read-only DB en OpenShift-logs.')
result = subprocess.run(['oc', 'get', 'secret', 'ai-access', '-n', args.namespace, '-o', 'json'], capture_output=True, check=True)
data = json.loads(result.stdout)
token = base64.b64decode(data['data']['AI_ACCESS_TOKEN'])
subprocess.run(['pbcopy'], input=token, check=True)
print('Token staat op het klembord. Plak rechtstreeks in het gemaskeerde veld /api/auth/agent-login (Software Factory en Assistent: /api/v1/auth/agent-login). Wis het klembord na gebruik.')
