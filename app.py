from flask import Flask, jsonify, render_template
from urllib.request import Request, urlopen
from io import BytesIO
import pdfplumber, time, re

app=Flask(__name__)
URL='https://multipass.wizzair.com/aycf-availability.pdf'
cache={'at':0,'routes':[],'period':'','updated':''}

def fetch_routes():
    if cache['routes'] and time.time()-cache['at']<3600: return cache
    req=Request(URL,headers={'User-Agent':'Mozilla/5.0 WizzRouteExplorer/1.0'})
    with urlopen(req,timeout=25) as response: raw=response.read(5_000_000)
    routes=set(); header=[]
    with pdfplumber.open(BytesIO(raw)) as pdf:
        for page in pdf.pages:
            text=page.extract_text() or ''
            if not header: header=text.splitlines()[:8]
            for table in page.extract_tables():
                for row in table:
                    cells=[re.sub(r'\s+',' ',str(c or '')).strip() for c in row]
                    for i in range(0,len(cells)-1,2):
                        a,b=cells[i:i+2]
                        if a and b and a.lower() not in ('departure city','departure') and b.lower() not in ('arrival city','arrival') and len(a)<65 and len(b)<65:
                            routes.add((a,b))
    if not routes: raise ValueError('Keine Strecken aus PDF extrahierbar')
    cache.update(at=time.time(),routes=sorted(routes),period=' | '.join(x for x in header if 'Departure period:' in x),updated=' | '.join(x for x in header if 'Last run:' in x))
    return cache

@app.get('/health')
def health(): return jsonify({'status':'ok'})

@app.get('/')
def index(): return render_template('index.html')

@app.get('/api/routes')
def api_routes():
    try:
        data=fetch_routes()
        return jsonify({'routes':data['routes'],'period':data['period'],'updated':data['updated'],'source':URL,'count':len(data['routes']),'note':'Streckenliste, keine einzelnen Flugzeiten oder garantierten Abo-Sitze'})
    except Exception as exc:
        return jsonify({'error':str(exc),'source':URL}),503

if __name__=='__main__': app.run(debug=True,port=5000)
