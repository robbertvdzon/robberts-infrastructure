import unittest

from preview_reconciler import (
    ORPHAN_AT,
    ORPHAN_COUNT,
    OWNER_LABEL,
    OWNER_VALUE,
    PR_LABEL,
    REPOSITORY_LABEL,
    Metrics,
    Reconciler,
    KubernetesClient,
    identify_deleting_application,
)


def namespace(name: str, repository: str, number: int, annotations=None):
    return {
        "metadata": {
            "name": name,
            "labels": {
                OWNER_LABEL: OWNER_VALUE,
                REPOSITORY_LABEL: repository,
                PR_LABEL: str(number),
            },
            "annotations": annotations or {},
        }
    }


class FakeGitHub:
    def __init__(self, open_prs=None, fail=False):
        self.open_prs = open_prs or {}
        self.fail = fail

    def open_pull_requests(self, repository):
        if self.fail:
            raise RuntimeError("unavailable")
        return set(self.open_prs.get(repository, set()))

    def pull_request_is_open(self, repository, number):
        if self.fail:
            raise RuntimeError("unavailable")
        return number in self.open_prs.get(repository, set())


class FakeKubernetes:
    def __init__(self, namespaces, applications=None, existing_namespaces=None):
        self.namespaces = namespaces
        self.applications = applications or []
        self.existing_namespaces = set(existing_namespaces or [])
        self.patches = []
        self.deleted = []
        self.finalizer_patches = []

    def owned_namespaces(self):
        return self.namespaces

    def patch_annotations(self, name, annotations):
        self.patches.append((name, annotations))

    def delete_namespace(self, name):
        if name not in self.deleted:
            self.deleted.append(name)

    def preview_applications(self):
        return self.applications

    def namespace_exists(self, name):
        return name in self.existing_namespaces

    def patch_application_finalizers(self, name, finalizers):
        self.finalizer_patches.append((name, finalizers))


class ReconcilerTest(unittest.TestCase):
    def test_delete_uses_kubernetes_delete_options(self):
        calls = []
        client = object.__new__(KubernetesClient)
        client._request = lambda method, path, body: calls.append((method, path, body))

        client.delete_namespace("hkh-pr-42")

        self.assertEqual(
            [(
                "DELETE",
                "/api/v1/namespaces/hkh-pr-42",
                {"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Foreground"},
            )],
            calls,
        )

    def test_github_outage_never_mutates_cluster(self):
        kube = FakeKubernetes([namespace("hkh-pr-7", "hkh", 7)])
        Reconciler(FakeGitHub(fail=True), kube, Metrics(), 60, lambda: 100).run_once()
        self.assertEqual([], kube.patches)
        self.assertEqual([], kube.deleted)

    def test_requires_two_observations_and_grace_before_delete(self):
        item = namespace("hkh-pr-7", "hkh", 7)
        kube = FakeKubernetes([item])
        reconciler = Reconciler(FakeGitHub(), kube, Metrics(), 60, lambda: 100)
        reconciler.run_once()
        self.assertEqual(("hkh-pr-7", {ORPHAN_AT: "100", ORPHAN_COUNT: "1"}), kube.patches[-1])
        self.assertEqual([], kube.deleted)

        item["metadata"]["annotations"] = {ORPHAN_AT: "100", ORPHAN_COUNT: "1"}
        Reconciler(FakeGitHub(), kube, Metrics(), 60, lambda: 161).run_once()
        self.assertEqual(["hkh-pr-7"], kube.deleted)

    def test_open_pr_cancels_stale_orphan_state(self):
        item = namespace(
            "hkh-autopilot-pr-12",
            "hkh-autopilot",
            12,
            {ORPHAN_AT: "10", ORPHAN_COUNT: "2"},
        )
        kube = FakeKubernetes([item])
        github = FakeGitHub({"hkh-autopilot": {12}})
        Reconciler(github, kube, Metrics(), 60, lambda: 100).run_once()
        self.assertEqual(("hkh-autopilot-pr-12", {ORPHAN_AT: None, ORPHAN_COUNT: None}), kube.patches[-1])
        self.assertEqual([], kube.deleted)

    def test_invalid_prefix_or_label_is_never_deleted(self):
        invalid = namespace("hkh-production", "hkh", 99)
        mismatched = namespace("pnf-pr-8", "hkh", 8)
        kube = FakeKubernetes([invalid, mismatched])
        Reconciler(FakeGitHub(), kube, Metrics(), 0, lambda: 100).run_once()
        self.assertEqual([], kube.patches)
        self.assertEqual([], kube.deleted)

    def test_cleanup_is_idempotent_after_namespace_disappears(self):
        item = namespace("pnf-pr-9", "personal-news-feed-by-claude-code", 9, {ORPHAN_AT: "1", ORPHAN_COUNT: "1"})
        kube = FakeKubernetes([item])
        reconciler = Reconciler(FakeGitHub(), kube, Metrics(), 1, lambda: 10)
        reconciler.run_once()
        kube.namespaces = []
        reconciler.run_once()
        self.assertEqual(["pnf-pr-9"], kube.deleted)

    def test_identifies_only_deleting_preview_applications(self):
        application = {
            "metadata": {
                "name": "hkh-preview-42",
                "deletionTimestamp": "2026-08-07T10:00:00Z",
                "labels": {"preview-pr": "42"},
            },
            "spec": {"destination": {"namespace": "hkh-pr-42"}},
        }
        self.assertEqual(
            ("hkh-preview-42", "hkh-pr-42"),
            identify_deleting_application(application),
        )
        application["metadata"].pop("deletionTimestamp")
        self.assertIsNone(identify_deleting_application(application))

    def test_reaps_argocd_finalizer_only_after_namespace_is_gone(self):
        application = {
            "metadata": {
                "name": "hkh-preview-42",
                "deletionTimestamp": "2026-08-07T10:00:00Z",
                "labels": {"preview-pr": "42"},
                "finalizers": [
                    "resources-finalizer.argocd.argoproj.io",
                    "keep.example/finalizer",
                ],
            },
            "spec": {"destination": {"namespace": "hkh-pr-42"}},
        }
        kube = FakeKubernetes([], [application])
        Reconciler(FakeGitHub(), kube, Metrics(), 60, lambda: 100).run_once()
        self.assertEqual([("hkh-preview-42", ["keep.example/finalizer"])], kube.finalizer_patches)

        kube = FakeKubernetes([], [application], {"hkh-pr-42"})
        Reconciler(FakeGitHub(), kube, Metrics(), 60, lambda: 100).run_once()
        self.assertEqual([], kube.finalizer_patches)

    def test_finalizer_patch_uses_argocd_namespaced_api(self):
        calls = []
        client = object.__new__(KubernetesClient)
        client._request = lambda method, path, body: calls.append((method, path, body))

        client.patch_application_finalizers("hkh-preview-42", [])

        self.assertEqual(
            [(
                "PATCH",
                "/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/hkh-preview-42",
                {"metadata": {"finalizers": []}},
            )],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
