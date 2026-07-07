#!/usr/bin/env bash
# Grammar A/B (workstream 6 / grammar adoption gate): does llama.cpp
# json_schema-constrained decoding improve structured-output validity vs
# free-form prompting? Tests TWO complexity levels (flat + nested) because the
# gap only shows up on hard schemas. Python does all HTTP+JSON.
set -uo pipefail
MODEL="${1:?model gguf path}"; LABEL="${2:-model}"
SERVER=/home/kellogg/llm/llama.cpp/build/bin/llama-server
PORT="${PORT:-8899}"; NGL="${NGL:-999}"; BASE="http://127.0.0.1:${PORT}"

"$SERVER" -m "$MODEL" -ngl "$NGL" -c 8192 -fa on --host 127.0.0.1 --port "$PORT" \
  >/tmp/gab-$LABEL.log 2>&1 &
SPID=$!; trap 'kill $SPID 2>/dev/null' EXIT
for _ in $(seq 1 120); do curl -sf "$BASE/health" >/dev/null 2>&1 && break; kill -0 $SPID 2>/dev/null || { echo "server died"; tail -6 /tmp/gab-$LABEL.log; exit 1; }; sleep 1; done

BASE="$BASE" LABEL="$LABEL" python3 - <<'PY'
import os, json, re, urllib.request
BASE=os.environ["BASE"]; LABEL=os.environ["LABEL"]

flat={"type":"object","required":["symbol","severity","line","rationale"],
      "properties":{"symbol":{"type":"string"},
                    "severity":{"type":"string","enum":["low","medium","high"]},
                    "line":{"type":"integer"},"rationale":{"type":"string"}}}
nested={"type":"object","required":["file","findings","summary"],
        "properties":{
          "file":{"type":"string"},
          "findings":{"type":"array","minItems":2,"items":{
             "type":"object","required":["symbol","severity","line","fix"],
             "properties":{"symbol":{"type":"string"},
                           "severity":{"type":"string","enum":["low","medium","high"]},
                           "line":{"type":"integer"},"fix":{"type":"string"}}}},
          "summary":{"type":"object","required":["total","worst"],
             "properties":{"total":{"type":"integer"},
                           "worst":{"type":"string","enum":["low","medium","high"]}}}}}

bugs=[
 "Null-pointer deref in parseConfig when the file is empty, around line 88.",
 "Unbounded retry loop in retryFetch (line 214) spins forever on HTTP 500.",
 "SQL built by string concat in getUser at line 42 — injection risk.",
 "Race on the shared counter in Worker.tick, line 130, no lock.",
 "Password compared with == instead of constant-time, line 77.",
 "Off-by-one reading the last row in loadCsv, line 305.",
 "Unclosed file handle in exportReport, line 19, leaks on error.",
 "Integer overflow multiplying width*height in alloc, line 256.",
 "Missing await on saveState in shutdown, line 401 — data loss.",
 "Regex catastrophic backtracking in validateEmail, line 12.",
 "Hardcoded API host in client init, line 5 — not configurable.",
 "Division by zero when list is empty in average(), line 60.",
]
flat_instr=(" Respond with ONLY a JSON object: symbol (string), severity "
            "(low|medium|high), line (integer), rationale (string). No prose.")
def nested_prompt(b1,b2):
    return (f"Review file util.py. Two issues: (1) {b1} (2) {b2}. Respond with ONLY a JSON "
            "object: file (string), findings (array of >=2 objects each with symbol[string], "
            "severity[low|medium|high], line[integer], fix[string]), and summary (object with "
            "total[integer] and worst[low|medium|high]). No prose.")

def call(prompt, schema):
    body={"prompt":prompt,"n_predict":320,"temperature":0.2,"cache_prompt":False}
    if schema is not None: body["json_schema"]=schema
    req=urllib.request.Request(BASE+"/completion",
        data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()).get("content","")

def extract(s):
    s=s.strip(); m=re.search(r"\{.*\}", s, re.S); return m.group(0) if m else s

def check(o, schema):
    if not isinstance(o,dict): return False
    for k in schema.get("required",[]):
        if k not in o: return False
    for k,spec in schema.get("properties",{}).items():
        if k not in o: continue
        t=spec.get("type"); v=o[k]
        if t=="string" and not isinstance(v,str): return False
        if t=="integer" and not isinstance(v,int): return False
        if t=="array":
            if not isinstance(v,list) or len(v)<spec.get("minItems",0): return False
            for it in v:
                if not check(it, spec["items"]): return False
        if t=="object" and not check(v, spec): return False
        if "enum" in spec and v not in spec["enum"]: return False
    return True

def valid(s, schema):
    try: return check(json.loads(extract(s)), schema)
    except Exception: return False

def run(label, tasks, schema):
    out={}
    for mode,con in (("free",None),("constrained",schema)):
        ok=0
        for t in tasks:
            try:
                if valid(call(t,con), schema): ok+=1
            except Exception: pass
        out[mode]=ok
    n=len(tasks)
    print(f"[{label}] free={out['free']}/{n} ({100*out['free']//n}%)  "
          f"constrained={out['constrained']}/{n} ({100*out['constrained']//n}%)  "
          f"delta={out['constrained']-out['free']:+d}")

flat_tasks=[b+flat_instr for b in bugs]
nested_tasks=[nested_prompt(bugs[i], bugs[(i+1)%len(bugs)]) for i in range(len(bugs))]
print(f"== grammar A/B: {LABEL} ==  (n={len(bugs)} per level)")
run("flat schema  ", flat_tasks, flat)
run("nested schema", nested_tasks, nested)
PY
kill $SPID 2>/dev/null; trap - EXIT
