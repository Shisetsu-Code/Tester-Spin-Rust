"""Sanitized, game-scoped request evidence from authorized manual captures."""
import json
from urllib.parse import urlparse

def purchase_modes_from_har(path, symbol):
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    count=0
    for entry in data.get("log",{}).get("entries",[]):
        request=entry.get("request",{});url=urlparse(request.get("url",""))
        if request.get("method")!="POST" or url.scheme!="https" or url.hostname!="rmpdemo.kaga88.com" or url.path!="/kaga/command/spin":continue
        try:body=json.loads(request.get("postData",{}).get("text",""))
        except (ValueError,TypeError):continue
        if isinstance(body,dict) and body.get("gn")==symbol and body.get("pos")==[1]:count+=1
    if not count:return []
    return [{"id":"BUY_POS_1","kind":"PURCHASE","pos":[1],"source":"manual-har","observed":True,
        "validated":False,"executable":False,"coverage_required":True,"observed_requests":count,
        "request_shape":{"pos":[1]},"cost_multiplier":None}]
