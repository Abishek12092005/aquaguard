import json, urllib.request, urllib.parse
BASE="http://127.0.0.1:5000/api/v1"
b=json.dumps({"email":"step31test@aquaguard.test","password":"Str0ngPass!2026"}).encode()
r=urllib.request.Request(BASE+"/auth/login",data=b,method="POST"); r.add_header("Content-Type","application/json")
t=json.loads(urllib.request.urlopen(r,timeout=30).read())["data"]["tokens"]["access_token"]
q=urllib.request.Request(BASE+"/locations/search?q=Meenakshi%20Temple&limit=5"); q.add_header("Authorization","Bearer "+t)
print(json.dumps(json.loads(urllib.request.urlopen(q,timeout=120).read()))[:900])
