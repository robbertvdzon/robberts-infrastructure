# Wachtwoord wijzigen/roteren:
#   export KUBECONFIG=~/okd-sno/sno/auth/kubeconfig   # admin nodig voor kubeseal --fetch-cert
#   kubeseal --fetch-cert > manifests/smb-timemachine/cluster-cert.pem
#   oc create secret generic samba-timemachine-credentials -n smb-timemachine \
#     --from-literal=SAMBA_PASSWORD='<nieuw-wachtwoord>' --dry-run=client -o yaml | \
#     kubeseal --cert manifests/smb-timemachine/cluster-cert.pem --format yaml \
#     > manifests/smb-timemachine/sealed-secret-credentials.yaml
#   git add manifests/smb-timemachine/sealed-secret-credentials.yaml
#   git commit -m "smb-timemachine: roteer wachtwoord" && git push
# ArgoCD synct, de controller decrypt, de pod pikt 'm op na:
#   oc rollout restart deployment/samba-timemachine -n smb-timemachine
