"""Real-browser demo fetches, used only after a challenged HTTP login."""
import json
from urllib.parse import urlsplit, urlencode

class BrowserResponse:
    def __init__(self,value):self.status_code=value['status'];self.text=value['text']
    def raise_for_status(self):
        if self.status_code>=400:raise ValueError(f'3 Oaks: browser HTTP {self.status_code}')
    def json(self):return json.loads(self.text)

class BrowserDemoTransport:
    def __init__(self,public_url):
        self.public_url=public_url;self.playwright=None;self.browser=None;self.page=None
    def _open(self,url):
        from playwright.sync_api import sync_playwright
        self.playwright=sync_playwright().start()
        try:
            try:self.browser=self.playwright.chromium.launch(headless=True,channel='msedge')
            except Exception:self.browser=self.playwright.chromium.launch(headless=True)
            self.page=self.browser.new_page()
            self.page.goto(url,wait_until='domcontentloaded',timeout=30000)
        except Exception:
            self.close();raise
    def post(self,url,*,params,data,timeout,headers):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname!='betman-demo.head.3oaks.com' or not parsed.path.endswith('/demo/'):
            raise ValueError('3 Oaks: endpoint de navegador fuera del contrato demo')
        if self.page is None:self._open(url)
        # Execute one request. A timeout never retries a paid operation.
        value=self.page.evaluate('''async ({url,body,timeout}) => {
            const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeout);
            try {const r=await fetch(url,{method:'POST',headers:{'Content-Type':'text/plain'},body,signal:controller.signal});
                return {status:r.status,text:await r.text()};}finally{clearTimeout(timer);}
        }''',{'url':url+'?'+urlencode(params),'body':data,'timeout':int(timeout*1000)})
        return BrowserResponse(value)
    def close(self):
        try:
            if self.browser:self.browser.close()
        finally:
            if self.playwright:self.playwright.stop()
            self.page=None;self.browser=None;self.playwright=None
