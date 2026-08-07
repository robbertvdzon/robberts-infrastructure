#!/usr/bin/env python3
"""Safely reconciles disposable OpenShift PR-preview namespaces."""

from __future__ import annotations

import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


OWNER_LABEL = "preview.vdzonsoftware.nl/managed-by"
OWNER_VALUE = "preview-reconciler"
REPOSITORY_LABEL = "preview.vdzonsoftware.nl/repository"
PR_LABEL = "preview.vdzonsoftware.nl/pr-number"
ORPHAN_AT = "preview.vdzonsoftware.nl/orphan-observed-at"
ORPHAN_COUNT = "preview.vdzonsoftware.nl/orphan-observation-count"


@dataclass(frozen=True)
class Rule:
    repository: str
    pattern: re.Pattern[str]


RULES = (
    Rule("personal-news-feed-by-claude-code", re.compile(r"^pnf-pr-(\d+)$")),
    Rule("hkh", re.compile(r"^hkh-pr-(\d+)$")),
    Rule("hkh-autopilot", re.compile(r"^hkh-autopilot-pr-(\d+)$")),
)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.orphaned = 0
        self.oldest_orphan_seconds = 0.0
        self.deleted_total = 0
        self.cleanup_failures_total = 0
        self.github_failures_total = 0
        self.invalid_namespaces_total = 0

    def update_gauges(self, active: int, orphaned: int, oldest: float) -> None:
        with self._lock:
            self.active = active
            self.orphaned = orphaned
            self.oldest_orphan_seconds = oldest

    def increment(self, field: str) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)

    def render(self) -> str:
        with self._lock:
            values = dict(vars(self))
        values.pop("_lock", None)
        return "".join(
            f"preview_reconciler_{name} {value}\n" for name, value in values.items()
        )


def log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


class GitHubClient:
    def __init__(self, owner: str, token: str, timeout: int = 20) -> None:
        self.owner = owner
        self.token = token
        self.timeout = timeout

    def _get(self, path: str) -> object:
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "vdzon-preview-reconciler",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def open_pull_requests(self, repository: str) -> set[int]:
        result: set[int] = set()
        for page in range(1, 21):
            pulls = self._get(
                f"/repos/{self.owner}/{repository}/pulls?state=open&per_page=100&page={page}"
            )
            if not isinstance(pulls, list):
                raise RuntimeError(f"Unexpected GitHub response for {repository}")
            result.update(int(pull["number"]) for pull in pulls)
            if len(pulls) < 100:
                return result
        raise RuntimeError(f"More than 2000 open pull requests in {repository}")

    def pull_request_is_open(self, repository: str, number: int) -> bool:
        pull = self._get(f"/repos/{self.owner}/{repository}/pulls/{number}")
        return isinstance(pull, dict) and pull.get("state") == "open"


class KubernetesClient:
    def __init__(self) -> None:
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self.base_url = f"https://{host}:{port}"
        serviceaccount = "/var/run/secrets/kubernetes.io/serviceaccount"
        with open(f"{serviceaccount}/token", encoding="utf-8") as token_file:
            self.token = token_file.read().strip()
        self.context = ssl.create_default_context(cafile=f"{serviceaccount}/ca.crt")

    def _request(self, method: str, path: str, body: object | None = None) -> object:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/merge-patch+json",
            },
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=20) as response:
                return json.load(response) if response.length != 0 else {}
        except urllib.error.HTTPError as error:
            if method == "DELETE" and error.code == 404:
                return {}
            raise

    def owned_namespaces(self) -> list[dict]:
        selector = urllib.parse.quote(f"{OWNER_LABEL}={OWNER_VALUE}")
        response = self._request("GET", f"/api/v1/namespaces?labelSelector={selector}")
        if not isinstance(response, dict):
            raise RuntimeError("Unexpected Kubernetes namespace response")
        return list(response.get("items", []))

    def patch_annotations(self, namespace: str, annotations: dict[str, str | None]) -> None:
        self._request(
            "PATCH",
            f"/api/v1/namespaces/{urllib.parse.quote(namespace)}",
            {"metadata": {"annotations": annotations}},
        )

    def delete_namespace(self, namespace: str) -> None:
        self._request(
            "DELETE",
            f"/api/v1/namespaces/{urllib.parse.quote(namespace)}",
            {"propagationPolicy": "Foreground"},
        )


def identify(namespace: dict) -> tuple[Rule, int] | None:
    metadata = namespace.get("metadata", {})
    name = str(metadata.get("name", ""))
    labels = metadata.get("labels", {}) or {}
    if labels.get(OWNER_LABEL) != OWNER_VALUE:
        return None
    for rule in RULES:
        match = rule.pattern.fullmatch(name)
        if not match:
            continue
        number = int(match.group(1))
        if labels.get(REPOSITORY_LABEL) != rule.repository:
            return None
        if labels.get(PR_LABEL) != str(number):
            return None
        return rule, number
    return None


class Reconciler:
    def __init__(
        self,
        github: GitHubClient,
        kubernetes: KubernetesClient,
        metrics: Metrics,
        grace_seconds: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.github = github
        self.kubernetes = kubernetes
        self.metrics = metrics
        self.grace_seconds = grace_seconds
        self.now = now

    def run_once(self) -> None:
        try:
            open_prs = {
                rule.repository: self.github.open_pull_requests(rule.repository)
                for rule in RULES
            }
        except Exception as error:  # fail closed: never mutate on uncertain GitHub state
            self.metrics.increment("github_failures_total")
            log("github_unavailable", error=type(error).__name__)
            return

        try:
            namespaces = self.kubernetes.owned_namespaces()
        except Exception as error:
            self.metrics.increment("cleanup_failures_total")
            log("kubernetes_unavailable", error=type(error).__name__)
            return

        active = 0
        orphaned = 0
        oldest = 0.0
        current_time = self.now()

        for namespace in namespaces:
            metadata = namespace.get("metadata", {})
            name = str(metadata.get("name", ""))
            identity = identify(namespace)
            if identity is None:
                self.metrics.increment("invalid_namespaces_total")
                log("namespace_skipped", namespace=name, reason="identity_mismatch")
                continue
            rule, number = identity
            annotations = metadata.get("annotations", {}) or {}
            if number in open_prs[rule.repository]:
                active += 1
                if ORPHAN_AT in annotations or ORPHAN_COUNT in annotations:
                    self.kubernetes.patch_annotations(
                        name, {ORPHAN_AT: None, ORPHAN_COUNT: None}
                    )
                    log("orphan_state_cleared", namespace=name)
                continue

            orphaned += 1
            try:
                first_seen = float(annotations.get(ORPHAN_AT, ""))
                observations = int(annotations.get(ORPHAN_COUNT, "0"))
            except ValueError:
                first_seen = 0.0
                observations = 0

            if first_seen <= 0:
                self.kubernetes.patch_annotations(
                    name, {ORPHAN_AT: str(current_time), ORPHAN_COUNT: "1"}
                )
                log("orphan_observed", namespace=name, observation=1)
                continue

            age = max(0.0, current_time - first_seen)
            oldest = max(oldest, age)
            observations += 1
            if age < self.grace_seconds:
                self.kubernetes.patch_annotations(
                    name, {ORPHAN_COUNT: str(observations)}
                )
                log(
                    "orphan_waiting",
                    namespace=name,
                    observation=observations,
                    age_seconds=int(age),
                )
                continue

            try:
                still_open = self.github.pull_request_is_open(rule.repository, number)
            except Exception as error:
                self.metrics.increment("github_failures_total")
                log(
                    "delete_recheck_failed",
                    namespace=name,
                    error=type(error).__name__,
                )
                continue
            if still_open:
                self.kubernetes.patch_annotations(
                    name, {ORPHAN_AT: None, ORPHAN_COUNT: None}
                )
                log("delete_cancelled_pr_open", namespace=name)
                continue

            try:
                self.kubernetes.delete_namespace(name)
                self.metrics.increment("deleted_total")
                log(
                    "namespace_deleted",
                    namespace=name,
                    repository=rule.repository,
                    pull_request=number,
                    observations=observations,
                    age_seconds=int(age),
                )
            except Exception as error:
                self.metrics.increment("cleanup_failures_total")
                log("namespace_delete_failed", namespace=name, error=type(error).__name__)

        self.metrics.update_gauges(active, orphaned, oldest)
        log("reconciliation_complete", active=active, orphaned=orphaned)


def start_metrics_server(metrics: Metrics, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/healthz", "/metrics"):
                self.send_error(404)
                return
            body = b"ok\n" if self.path == "/healthz" else metrics.render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    interval = int(os.environ.get("INTERVAL_SECONDS", "180"))
    grace = int(os.environ.get("GRACE_SECONDS", "600"))
    metrics = Metrics()
    start_metrics_server(metrics, int(os.environ.get("METRICS_PORT", "8080")))
    reconciler = Reconciler(
        GitHubClient(os.environ.get("GITHUB_OWNER", "robbertvdzon"), token),
        KubernetesClient(),
        metrics,
        grace,
    )
    log("reconciler_started", interval_seconds=interval, grace_seconds=grace)
    while True:
        reconciler.run_once()
        time.sleep(interval)


if __name__ == "__main__":
    main()
