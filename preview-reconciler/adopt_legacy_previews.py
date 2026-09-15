#!/usr/bin/env python3
"""Adopt only empty, closed legacy previews; default is a reviewable dry run."""
import argparse
import json
import subprocess
from preview_reconciler import RULES, OWNER_LABEL, OWNER_VALUE, REPOSITORY_LABEL, PR_LABEL


def read(*args):
    return json.loads(subprocess.check_output(args, text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    namespaces = read("oc", "get", "namespaces", "-o", "json")["items"]
    applications = read("oc", "get", "applications", "-n", "argocd", "-o", "json")["items"]
    for namespace in namespaces:
        metadata = namespace["metadata"]
        name = metadata["name"]
        if metadata.get("labels", {}).get(OWNER_LABEL) == OWNER_VALUE or metadata.get("deletionTimestamp"):
            continue
        matches = [(rule, rule.pattern.fullmatch(name)) for rule in RULES if rule.pattern.fullmatch(name)]
        if len(matches) != 1:
            continue
        rule, match = matches[0]
        number = match.group(1)
        # An API failure aborts adoption. Never infer closure from a missing/error response.
        pr = read("gh", "api", f"repos/robbertvdzon/{rule.repository}/pulls/{number}")
        owners = [app for app in applications if app.get("spec", {}).get("destination", {}).get("namespace") == name]
        matching_owner = any(app.get("spec", {}).get("source", {}).get("repoURL", "").removesuffix(".git") == f"https://github.com/robbertvdzon/{rule.repository}" and app.get("metadata", {}).get("labels", {}).get("preview-pr") == number for app in owners)
        if pr.get("state") == "open":
            if not matching_owner:
                print(f"SKIP {name}: open PR without verified ArgoCD owner")
                continue
        elif pr.get("state") == "closed":
            workloads = read("oc", "get", "all,pvc", "-n", name, "-o", "json")["items"]
            if workloads or owners:
                print(f"SKIP {name}: resources remain; review required")
                continue
        else:
            raise RuntimeError("Unknown PR state")
        print(f"{'ADOPT' if options.apply else 'WOULD ADOPT'} {name}: PR {number} {pr['state']}")
        if options.apply:
            subprocess.run(["oc", "label", "namespace", name, f"{OWNER_LABEL}={OWNER_VALUE}", f"{REPOSITORY_LABEL}={rule.repository}", f"{PR_LABEL}={number}", "--overwrite"], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
