#!/usr/bin/env bash
# Nexus between three local unix users over a throwaway key-only sshd on 127.0.0.1:2222.
# Needs sudo (creates users nxhub, nxa, nxb). Never touches the system sshd.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd); w=/tmp/nexus-test; sudo rm -rf $w; mkdir -p $w; chmod 755 $w
for u in nxhub nxa nxb; do id $u >/dev/null 2>&1 || sudo useradd -m -s /bin/bash $u; sudo usermod -p '*' $u; done  # '*': unlocked but no password exists
ssh-keygen -q -t ed25519 -N '' -f $w/hostkey
cat > $w/sshd_config <<C
Port 2222
ListenAddress 127.0.0.1
HostKey $w/hostkey
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers nxhub
PidFile $w/sshd.pid
C
sudo /usr/sbin/sshd -t -f $w/sshd_config
sudo mkdir -p /run/sshd; sudo /usr/sbin/sshd -f $w/sshd_config -E $w/sshd.log
trap 'sudo kill $(cat $w/sshd.pid) 2>/dev/null || true' EXIT
sudo -u nxhub bash -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && : > ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
for u in nxa nxb; do
  sudo -u $u bash -c 'mkdir -p ~/.ssh && rm -f ~/.ssh/id_ed25519* ~/.ssh/known_hosts && ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519'
  sudo cat /home/$u/.ssh/id_ed25519.pub | sudo -u nxhub tee -a /home/nxhub/.ssh/authorized_keys >/dev/null
done
cat > $w/graph.yaml <<G
hosts:
  hub:  {addr: 127.0.0.1, user: nxhub, port: 2222, kind: desktop}
  hosta: {addr: 127.0.0.1, user: nxa, port: 2222, kind: desktop}
  hostb: {addr: 127.0.0.1, user: nxb, port: 2222, kind: phone}
meshes:
  t: {type: ssh, hub: hub, root: ~/.familia/nexus, identity: ~/.ssh/id_ed25519, host_key_policy: accept-new, members: [hub, hosta, hostb]}
G
cp -r $here/scripts $w/scripts; chmod -R a+rX $w/scripts $w/graph.yaml
N="python3 $w/scripts/nexus/nexus.py --graph $w/graph.yaml --transport t"
sudo -u nxa bash -c "head -c 5000000 /dev/urandom > ~/slot0.bin && sha256sum ~/slot0.bin"
sudo -u nxa -H $N --as hosta register
sudo -u nxb -H $N --as hostb register
echo "--- peers (from hostb)"; sudo -u nxb -H $N --as hostb peers
key=$(sudo -u nxa -H $N --as hosta put /home/nxa/slot0.bin --kind kv); echo "put key: $key"
echo "--- ls"; sudo -u nxb -H $N --as hostb ls
sudo -u nxb -H bash -c "cd ~ && $N --as hostb get ${key:0:12} ~/"
sudo -u nxb bash -c 'sha256sum ~/slot0.bin'
echo "--- negative: non-member, password-only user"
sudo -u nxb -H $N --as nobody peers 2>&1 || true
sudo useradd -m nxc 2>/dev/null || true
echo "--- negative: user with no authorized key (nxc) is refused, no password prompt"
sudo -u nxc -H bash -c "mkdir -p ~/.ssh && rm -f ~/.ssh/known_hosts ~/.ssh/id_ed25519* && ssh-keygen -q -t ed25519 -N '' -f ~/.ssh/id_ed25519 && $N --as hostb peers" 2>&1 | tail -1 || true
echo "--- sshd log (hub side)"; sudo grep -iE "Accepted|denied|password|invalid|Failed" $w/sshd.log | sort | uniq -c | tail -6 || true
