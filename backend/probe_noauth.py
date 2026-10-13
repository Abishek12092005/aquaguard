import urllib.request, json, time
BASE="http://127.0.0.1:5000/api/v1"
for p in ["/locations/country?q=India&limit=5"]:
    url=BASE+p
    t=time.time()
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            print(p, "status", r.status, "in", round(time.time()-t,1), "s")
    except Exception as e:
        print(p, "ERROR after", round(time.time()-t,1), "s:", type(e).__name__, e)
