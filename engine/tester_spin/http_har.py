"""Local HTTP exchange recording; raw demo sessions stay outside source control."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode

class HTTPHar:
    def __init__(self,path):
        self.path=Path(path)
        self.entries=[]

    def append(self,url,query,body,headers,response,elapsed):
        text=getattr(response,'text',None)
        if not isinstance(text,str):
            try:text=json.dumps(response.json(),ensure_ascii=False)
            except (ValueError,TypeError,AttributeError):text=''
        response_headers=getattr(response,'headers',{})
        if not hasattr(response_headers,'items'):response_headers={}
        version={1:'HTTP/1.0',2:'HTTP/1.1',3:'HTTP/2',30:'HTTP/3'}.get(getattr(response,'http_version',None),'')
        form=body if isinstance(body,str) else urlencode(body or {})
        request_mime=headers.get('Content-Type','application/x-www-form-urlencoded')
        response_mime=response_headers.get('Content-Type','application/json')
        if not isinstance(response_mime,str):response_mime='application/json'
        request={'method':'GET' if body is None else 'POST','url':url+('?' if '?' not in url else '&')+urlencode(query),
                 'httpVersion':version,'headers':[{'name':str(k),'value':str(v)} for k,v in headers.items()],
                 'queryString':[{'name':str(k),'value':str(v)} for k,v in query.items()],
                 'cookies':[],'headersSize':-1,'bodySize':len(form.encode())}
        if body is not None:
            request['postData']={'mimeType':request_mime,'text':form}
            if isinstance(body,dict) and request_mime=='application/x-www-form-urlencoded':
                request['postData']['params']=[{'name':str(k),'value':str(v)} for k,v in body.items()]
        self.entries.append({'startedDateTime':(datetime.now(timezone.utc)-timedelta(seconds=elapsed)).isoformat(),
            'time':elapsed*1000,'request':request,
            'response':{'status':response.status_code if type(response.status_code) is int else 0,'statusText':'','httpVersion':version,
                'headers':[{'name':str(k),'value':str(v)} for k,v in response_headers.items()],
                'cookies':[],'content':{'size':len(text.encode()),'mimeType':response_mime,'text':text},
                'redirectURL':'','headersSize':-1,'bodySize':len(text.encode())},
            'cache':{},'timings':{'send':0,'wait':elapsed*1000,'receive':0}})
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.har.tmp')
        temporary.write_text(json.dumps({'log':{'version':'1.2','creator':{'name':'Tester-Spin','version':'1'},'entries':self.entries}},ensure_ascii=False),encoding='utf8')
        temporary.replace(self.path)
