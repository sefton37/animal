#!/usr/bin/env bash
# Decorrelation gate (workstream 7 / Law 5 / pre-registration): run the seeded
# premise-review battery through several CAPABLE judge-LINEAGE local models, then
# compute per-model accuracy and pairwise co-failure phi. phi < 0.5 => the
# "diverse" seats genuinely decorrelate (not monoculture behind brand labels).
#
# Verdicts via /v1/chat/completions (--jinja applies each model's chat template)
# with a schema-constrained JSON verdict. Per-model max_tokens because reasoning
# models (gpt-oss) need room for their reasoning trace BEFORE the content JSON,
# while the slow partial-offload mistral needs a tight budget.
#
# Seats are 3 CAPABLE distinct lineages (OpenAI / Mistral / Qwen). The 3-4B jury
# models are excluded here: a prior run showed they DEGENERATE to all-"unsound"
# on premise review (too weak for this nuanced judgment) — a finding in itself,
# not a decorrelation signal. See results/cofailure-notes.md.
#
# Usage: bash cofailure.sh phase0/results/cofailure-battery.json
set -uo pipefail
BATTERY="${1:?battery json path}"
SERVER=/home/kellogg/llm/llama.cpp/build/bin/llama-server
PORT="${PORT:-8899}"; BASE="http://127.0.0.1:${PORT}"
OUT=/home/kellogg/dev/animal/phase0/results/cofailure
mkdir -p "$OUT"; rm -f "$OUT"/*.json
MDIR=/home/kellogg/dev/animal/var/models

# nick | gguf | ngl | max_tokens | extra-flags
MODELS=(
  "gpt-oss|$MDIR/judge-gpt-oss-20b/gpt-oss-20b-Q4_K_M.gguf|999|1024|"
  "mistral|$MDIR/auditor-mistral-24b/Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf|30|200|"
  "qwen-coder|$MDIR/coder-qwen3-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf|999|256|--n-cpu-moe 48"
)

for entry in "${MODELS[@]}"; do
  IFS='|' read -r nick gguf ngl mt extra <<< "$entry"
  [ -f "$gguf" ] || { echo "SKIP $nick (missing $gguf)"; continue; }
  echo ">> $nick (ngl=$ngl mt=$mt ${extra})"
  "$SERVER" -m "$gguf" -ngl "$ngl" -c 8192 -fa on --jinja $extra --host 127.0.0.1 --port "$PORT" >/tmp/cf-$nick.log 2>&1 &
  SPID=$!
  ok=""; for _ in $(seq 1 150); do curl -sf "$BASE/health" >/dev/null 2>&1 && { ok=1; break; }; kill -0 $SPID 2>/dev/null || break; sleep 1; done
  if [ -z "$ok" ]; then echo "  server failed:"; tail -4 /tmp/cf-$nick.log; kill $SPID 2>/dev/null; continue; fi
  BASE="$BASE" BATTERY="$BATTERY" MT="$mt" python3 - > "$OUT/$nick.json" <<'PY'
import os,json,re,urllib.request
BASE=os.environ["BASE"]; battery=json.load(open(os.environ["BATTERY"])); MT=int(os.environ["MT"])
schema={"type":"object","required":["verdict","reason"],
        "properties":{"verdict":{"type":"string","enum":["sound","unsound"]},"reason":{"type":"string"}}}
SYS=("You are a strict specification reviewer. You judge exactly one thing: whether the premise "
     "encoded by a spec's Definition-of-Done checks faithfully serves the user story, or whether an "
     "implementation could satisfy every check while still violating what the story wants.")
def review(c):
    user=(f'USER STORY:\n{c["user_story"]}\n\nDoD CHECKS:\n- '+"\n- ".join(c["dod_checks"])+
          f'\n\nThe checks encode this PREMISE:\n"{c["premise"]}"\n\n'
          'Is the premise SOUND (faithfully serves the story) or UNSOUND (checks could all pass '
          'while the story is violated)? Return JSON {verdict, reason}.')
    body={"messages":[{"role":"system","content":SYS},{"role":"user","content":user}],
          "temperature":0,"max_tokens":MT,
          "response_format":{"type":"json_schema","json_schema":{"name":"verdict","strict":True,"schema":schema}}}
    req=urllib.request.Request(BASE+"/v1/chat/completions",data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=240) as r:
        return json.loads(r.read())["choices"][0]["message"].get("content","") or ""
def parse(txt):
    try:
        m=re.search(r"\{.*\}", txt, re.S); o=json.loads(m.group(0) if m else txt)
        v=str(o.get("verdict","")).lower(); return v if v in ("sound","unsound") else "?"
    except Exception:
        t=txt.lower(); return "unsound" if "unsound" in t else ("sound" if "sound" in t else "?")
verdicts={}
for c in battery["cases"]:
    try: verdicts[c["id"]]=parse(review(c))
    except Exception: verdicts[c["id"]]="?"
print(json.dumps(verdicts))
PY
  kill $SPID 2>/dev/null; sleep 1
done

echo; echo "=== decorrelation matrix (capable seats) ==="
BATTERY="$BATTERY" OUT="$OUT" python3 - <<'PY'
import os,json,glob,math
battery=json.load(open(os.environ["BATTERY"])); OUT=os.environ["OUT"]
gt={c["id"]:c["ground_truth"] for c in battery["cases"]}; ids=list(gt)
models={os.path.basename(f)[:-5]:json.load(open(f)) for f in sorted(glob.glob(OUT+"/*.json"))}
names=list(models); err={}
nub=sum(v=='unsound' for v in gt.values())
print(f"cases: {len(ids)}  ({nub} unsound / {len(ids)-nub} sound)\n\nper-model:")
for n in names:
    ev=[1 if models[n].get(i,'?')!=gt[i] else 0 for i in ids]; err[n]=ev
    acc=round(100*(len(ids)-sum(ev))/len(ids))
    miss=sum(1 for i in ids if gt[i]=='unsound' and models[n].get(i)!='unsound')
    ab=sum(1 for i in ids if models[n].get(i)=='?')
    sv=sum(1 for i in ids if models[n].get(i)=='sound'); uv=sum(1 for i in ids if models[n].get(i)=='unsound')
    print(f"  {n:12s} acc={acc:3d}%  missed-bad={miss}/{nub}  abstain={ab}  (said sound={sv}/unsound={uv})")
def phi(a,b):
    n11=sum(1 for x,y in zip(a,b) if x==1 and y==1); n00=sum(1 for x,y in zip(a,b) if x==0 and y==0)
    n10=sum(1 for x,y in zip(a,b) if x==1 and y==0); n01=sum(1 for x,y in zip(a,b) if x==0 and y==1)
    d=math.sqrt((n11+n10)*(n11+n01)*(n00+n10)*(n00+n01)); return (n11*n00-n10*n01)/d if d else 0.0
print("\npairwise co-failure phi (error-vector correlation; <0.5 = decorrelated):")
mx=-1
for i,a in enumerate(names):
    for b in names[i+1:]:
        p=phi(err[a],err[b]); mx=max(mx,p)
        both=sum(1 for x,y in zip(err[a],err[b]) if x==1 and y==1)
        print(f"  {a:12s} x {b:12s}  phi={p:+.2f}  both-wrong={both}")
degen=[n for n in names if err[n].count(0)==0 or err[n].count(1)==0 or sum(1 for i in ids if models[n].get(i)=='?')>2]
print(f"\nmax phi = {mx:+.2f}  ->  GATE {'PASS' if mx<0.5 else 'FAIL'}"
      + (f"  [WARN: degenerate/abstaining seats {degen} — φ not meaningful for them]" if degen else "  [all seats non-degenerate]"))
PY
