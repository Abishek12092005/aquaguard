import urllib.request, json, urllib.parse, time
BASE="http://127.0.0.1:5000/api/v1"
def req(path, method="GET", body=None, token=None, timeout=300):
    url=BASE+path
    r=urllib.request.Request(url, method=method)
    r.add_header("Content-Type","application/json")
    if token: r.add_header("Authorization","Bearer "+token)
    d=json.dumps(body).encode() if body is not None else None
    t=time.time()
    try:
        with urllib.request.urlopen(r, data=d, timeout=timeout) as resp:
            print(path, "->", resp.status, "in", round(time.time()-t,1),"s", flush=True)
            return json.loads(resp.read())
    except Exception as e:
        print(path, "ERROR", round(time.time()-t,1),"s", type(e).__name__, e, flush=True)
        return None
lg=req("/auth/login","POST",{"email":"step31test@aquaguard.test","password":"Str0ngPass!2026"})
if not lg: raise SystemExit
tok=lg["data"]["tokens"]["access_token"]
c=req("/locations/country?q=India&limit=5", token=tok)
if c:
    print("KEYS:", list(c["data"].keys()), flush=True)
    print("COUNTRY:", json.dumps(c["data"].get("country"))[:200], flush=True)
    for s in c["data"].get("states",[]):
        print("STATE ITEM:", json.dumps(s)[:250], flush=True)
