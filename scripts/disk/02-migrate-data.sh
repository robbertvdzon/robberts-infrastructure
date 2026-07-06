#!/usr/bin/env bash
#
# Rsync /var/mnt/localpv (oude schijf) naar /mnt/localpv-new (nieuwe schijf),
# met een verificatiepas na afloop.
#
# Draai dit script twee keer bij grote datasets: de eerste run kan lang duren,
# de tweede run is een snelle incrementele rsync die verschillen oppakt
# (bv. bestanden die tijdens de eerste run nog geschreven werden — zorg dat
# workloads die op de schijf schrijven uit staan, zie
# ../../docs/disk-4tb-to-12tb-migration.md stap 2).

set -euo pipefail

NODE_HOST="${NODE_HOST:-192.168.178.64}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/okd-sno}"
SRC="/var/mnt/localpv"
DST="/mnt/localpv-new"

ssh_node() { ssh -i "$SSH_KEY" -o ConnectTimeout=5 "core@$NODE_HOST" "$@"; }

echo "[migrate] node: $NODE_HOST"
echo "[migrate] $SRC -> $DST"

ssh_node "sudo rsync -aHAX --numeric-ids --info=progress2 '$SRC/' '$DST/'"

echo
echo "[migrate] verificatie: bestandscount"
src_count=$(ssh_node "sudo find '$SRC' -type f | wc -l")
dst_count=$(ssh_node "sudo find '$DST' -type f | wc -l")
echo "       bron:  $src_count bestanden"
echo "       nieuw: $dst_count bestanden"

if [[ "$src_count" != "$dst_count" ]]; then
  echo "WAARSCHUWING: aantal bestanden verschilt — draai dit script nogmaals" \
       "(kan komen door bestanden die tijdens de rsync zijn bijgeschreven)." >&2
else
  echo "       ok: aantal bestanden komt overeen"
fi

echo
echo "[migrate] steekproef: 10 willekeurige bestanden vergelijken op checksum"
ssh_node "
  sudo find '$SRC' -type f | shuf -n 10 --random-source=/dev/zero | while read -r f; do
    rel=\"\${f#$SRC/}\"
    src_sum=\$(sudo sha256sum \"\$f\" | cut -d' ' -f1)
    dst_sum=\$(sudo sha256sum \"$DST/\$rel\" 2>/dev/null | cut -d' ' -f1 || echo MISSING)
    if [[ \"\$src_sum\" == \"\$dst_sum\" ]]; then
      echo \"       ok: \$rel\"
    else
      echo \"       MISMATCH: \$rel (bron=\$src_sum nieuw=\$dst_sum)\"
    fi
  done
"

echo
echo "[migrate] volledige verificatie (optioneel, kan lang duren bij 4TB+):"
echo "  diff <(ssh -i $SSH_KEY core@$NODE_HOST 'sudo find $SRC -type f | sort') \\"
echo "       <(ssh -i $SSH_KEY core@$NODE_HOST 'sudo find $DST -type f | sort')"
echo
echo "[migrate] als alles klopt: 03-cutover.sh"
