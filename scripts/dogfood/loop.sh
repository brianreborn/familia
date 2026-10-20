#!/bin/sh
# Autonomous dogfood loop: familia nodes draft fixes for open familia issues.
# Order: P0 (#95) -> priority-1 -> rest. One issue per iteration, harness alternates.
# Lands on main ONLY if acceptance passes and full pytest has no failures beyond the
# origin/main baseline. Never closes issues, never force-pushes, never touches
# pentest/security/ssh/keys/sudoers paths. Server launches hold the per-host big.lock.
# Usage: loop.sh [--once]   (state in ~/.local/state/familia/dogfood/)
set -u
REPO="${FAMILIA_REPO:-$HOME/familia-dogfood}"
ST="$HOME/.local/state/familia"; D="$ST/dogfood"; mkdir -p "$D"
GIVEUP="$ST/dogfood-giveup.jsonl"; GIT="git -c user.name=Brian\ Fundakowski\ Feldman -c user.email=brianisbornagain@gmail.com"
[ -d "$REPO/.git" ] || git clone -q https://github.com/brianreborn/familia "$REPO"
while :; do
  cd "$REPO" && git fetch -q origin && git checkout -q --detach origin/main
  n=$(cat "$D/iter" 2>/dev/null || echo 0); echo $((n+1)) > "$D/iter"
  h=$( [ $((n % 2)) = 0 ] && echo hermes || echo harness2 )
  python3 - "$D" > "$D/task.yaml" <<'PY' || { sleep 600; continue; }
import json,subprocess,sys,re,os,yaml
d=sys.argv[1]; tried=set(open(d+"/tried").read().split()) if os.path.exists(d+"/tried") else set()
iss=json.loads(subprocess.check_output(["gh","issue","list","-R","brianreborn/familia","-L","100","--json","number,title,body,labels"]))
bad=re.compile(r"pentest|security|ssh|sshd|key|sudo|NOPASSWD|privacy",re.I)
def pri(i):
    L=" ".join(l["name"] for l in i["labels"])+i["title"]
    return 0 if ("priority-0" in L or "P0" in L) else 1 if ("priority-1" in L or "P1" in L) else 2
c=[i for i in sorted(iss,key=lambda i:(pri(i),i["number"])) if str(i["number"]) not in tried and not bad.search(i["title"]+i["body"][:2000])]
if not c: open(d+"/tried","w").close(); sys.exit(1)
i=c[0]; open(d+"/tried","a").write(f"{i['number']}\n")
files=[f for f in dict.fromkeys(re.findall(r"[\w./-]+\.(?:py|sh|md|txt|yaml)",i["body"]+i["title"])) if os.path.isfile(f) and not bad.search(f) and not f.startswith("roles/")][:3]
if not files: files=["TESTING.md"]
t=re.sub(r"\D","",i["title"])
yaml.safe_dump([{"id":f"i{i['number']}","issue":f"#{i['number']}","goal":(i["title"]+"\n"+i["body"])[:3000],"files":files,"accept":"sh scripts/dogfood/pytest_vs_baseline.sh"}],sys.stdout)
PY
  id=$(sed -n 's/^  id: //p;s/^- id: //p' "$D/task.yaml" | head -1); num=${id#i}
  python3 scripts/dogfood/dispatch.py "$D/task.yaml" --harness "$h" --out "$D/runs" --max-wait 7200 >> "$D/loop.log" 2>&1
  r=$(grep "\"id\": \"$id\"" "$D/runs/results.jsonl" | tail -1)
  wt=/tmp/dogfood-wt-$id; ok=0; why=""
  if [ -z "$r" ]; then why="no result"
  elif ! echo "$r" | grep -q '"accept_rc": 0'; then why="acceptance/pytest failed or no change"
  elif (cd "$wt" && git diff --cached --name-only | grep -Eiq 'pentest|ssh|secur|key|sudo|roles/'); then why="touched forbidden path"
  else ok=1; fi
  model=$(echo "$r" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("model","?"))' 2>/dev/null)
  if [ $ok = 1 ]; then
    cd "$wt" && eval $GIT commit -q -m "\"dogfood: $id draft for #$num\" -m \"Drafted-by: familia $h/$model\"" \
      && git pull -q --rebase origin main && sh scripts/dogfood/pytest_vs_baseline.sh >/dev/null 2>&1 && git push -q origin HEAD:main \
      && git fetch -q origin && sha=$(git rev-parse HEAD) && git merge-base --is-ancestor "$sha" origin/main \
      && gh issue comment "$num" -R brianreborn/familia -b "familia dogfood: $h/$model drafted $(git rev-parse --short HEAD) on main (acceptance + full pytest passed). Needs human verification; not closing." >/dev/null \
      || { ok=0; why="commit/rebase/retest/push/verify failed"; }
  fi
  [ $ok = 1 ] || echo "{\"ts\":\"$(date -Is)\",\"issue\":$num,\"harness\":\"$h\",\"model\":\"$model\",\"reason\":\"$why\"}" >> "$GIVEUP"
  echo "$(date -Is) #$num $h ok=$ok $why" >> "$D/loop.log"; date -Is > "$D/last_iter"
  cd "$REPO"; git worktree remove --force "$wt" 2>/dev/null
  [ "${1:-}" = --once ] && exit 0
  sleep 60
done
