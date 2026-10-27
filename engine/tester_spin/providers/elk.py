"""Official ELK CAPI demo base executor; complete paid inventory stays unverified."""
import hashlib,json,re,secrets,time
from urllib.parse import urlsplit,parse_qs,urljoin
from xml.etree import ElementTree as ET
from curl_cffi import requests
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.providers.elk_evidence import convert_case,declared_modes,money
from tester_spin.providers.elk_bootstrap import extract_official_demo,official_script_url


def validate_launch(url,symbol):
    u=urlsplit(url);q=parse_qs(u.query)
    if (u.scheme!='https' or u.hostname!='gamelauncher-stage.contentmedia.eu' or u.port not in (None,443)
            or u.username or u.password or q.get('mode')!=['demo'] or q.get('operatorid')!=['44']
            or q.get('gameid')!=[symbol] or not re.fullmatch(r'\d+',symbol)):
        raise ValueError('PUBLIC_DEMO_IDENTITY_NOT_CONFIRMED')
    return q


def redact_xml(text):
    root=ET.fromstring(text)
    for node in root.iter():
        if node.tag=='gamesession':
            child=node.find('id')
            if child is not None:child.text='REDACTED'
            elif not list(node):node.text='REDACTED'
        if node.tag=='playerhash':node.text='REDACTED'
        for key in ('gamesession','extsession','clientseed'):
            if key in node.attrib:node.attrib[key]='REDACTED'
        if node.text and node.tag=='pubdata':node.text=re.sub(r'clientseed="[^"]*"','clientseed="REDACTED"',node.text)
    return ET.tostring(root,encoding='unicode')


def request_xml(attributes):
    return b'<?xml version="1.0"?>'+ET.tostring(ET.Element('request',attributes),encoding='utf-8')


class ElkProvider(CatalogProvider):
    key='elk';display_name='ELK Studios';catalog_url='https://www.elk-studios.com/games/'
    execution_supported=True;max_test_concurrency=1

    def __init__(self,data_root):
        super().__init__(data_root)
        self._launch_bindings={}

    def prepare_test_artifacts(self,game,*,timeout_s,stop_event,progress):
        # Preparation is best-effort in the scheduler.  Record failures in this
        # instance too, so test_game cannot fall back to stale on-disk metadata.
        self._launch_bindings[game.slug]={'error':'FRESH_PUBLIC_DEMO_BOOTSTRAP_REQUIRED'}
        try:
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            root=self.game_dir(game);path=root/'game.json'
            meta=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
            if meta.get('provider','elk')!='elk' or meta.get('slug',game.slug)!=game.slug:
                raise ValueError('PUBLIC_DEMO_METADATA_IDENTITY_MISMATCH')
            def fetch(url,limit):
                if stop_event.is_set():raise ValueError('STOP_REQUESTED')
                response=self.http.get(url,timeout=timeout_s,allow_redirects=False)
                if response.status_code!=200 or response.url!=url or len(response.content)>limit:
                    raise ValueError('OFFICIAL_DEMO_RESOURCE_REJECTED')
                return response.text
            html=fetch(game.url,4*1024*1024)
            script=official_script_url(game,game.url,html)
            source=fetch(script,2*1024*1024)
            binding=extract_official_demo(game,game.url,html,script,source)
            validate_launch(binding['client_url'],binding['symbol'])
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            meta.update(provider='elk',slug=game.slug,name=game.name,public_url=game.url,**binding)
            path.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
            game.symbol=binding['symbol']
            self._launch_bindings[game.slug]=binding
            progress('ELK: identidad demo vinculada a ficha y handler oficiales actuales.')
        except Exception as exc:
            message=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z_]+',str(exc)) else 'OFFICIAL_DEMO_BOOTSTRAP_FAILED'
            self._launch_bindings[game.slug]={'error':message}
            raise ValueError(message) from None

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        root=self.game_dir(game);capture=root/'tests'/(str(time.time_ns())+'-capture');capture.mkdir(parents=True)
        report={'slug':game.slug,'status':'PARCIAL','rounds':[],'declaredModes':[],'endpoint':''}
        client=requests.Session(impersonate='chrome');counter=0;session='';base='';versions={};parts=None
        def persist():(capture/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        def get(url):
            response=client.get(url,timeout=timeout_s)
            response.raise_for_status();return response
        def exchange(method,attributes):
            nonlocal counter,session
            counter+=1;body=request_xml(attributes)
            (capture/f'{counter:03d}-{method}-request.redacted.xml').write_text(redact_xml(body.decode()),encoding='utf8')
            response=client.post(base+'/'+method,data=body,
                params={'gl':'true','standalone':'false','iframe':'false'} if method=='init' else None,
                headers={'Content-Type':'text/xml; charset=UTF-8','X-CAPI-Version':'2.0','X-CAPI-RID':str(time.time_ns()//100000)+':1',
                         'X-CLIENT-Version':versions['game'],'X-ECF-Version':versions['ecf'],
                         'Origin':parts.scheme+'://'+parts.netloc,'Referer':parts.scheme+'://'+parts.netloc+parts.path},
                timeout=timeout_s,allow_redirects=False)
            if len(response.content)>8*1024*1024 or b'<!DOCTYPE' in response.content.upper():raise ValueError('XML_CONTRACT_LIMIT')
            if response.status_code!=200:raise ValueError('HTTP '+str(response.status_code)+' '+method)
            node=ET.fromstring(response.content)
            (capture/f'{counter:03d}-{method}-response.redacted.xml').write_text(redact_xml(response.text),encoding='utf8')
            if node.findtext('method')!=method or node.findtext('errorcode')!='0':raise ValueError('CAPI_METHOD_OR_RESPONSE_REJECTED')
            holder=node.find('gamesession')
            if holder is not None:
                value=holder.findtext('id') if list(holder) else holder.text
                if value:session=value.strip()
            return node
        try:
            binding=self._launch_bindings.get(game.slug,{})
            if binding.get('error') or not binding.get('client_url'):
                raise ValueError(binding.get('error','FRESH_PUBLIC_DEMO_BOOTSTRAP_REQUIRED'))
            meta=json.loads((root/'game.json').read_text(encoding='utf8'));launch=meta.get('client_url','')
            if launch!=binding['client_url'] or game.symbol!=binding['symbol']:
                raise ValueError('PUBLIC_DEMO_METADATA_IDENTITY_MISMATCH')
            q=validate_launch(launch,game.symbol)
            if stop_event.is_set():raise ValueError('STOP_REQUESTED')
            response=get(launch);parts=urlsplit(response.url);parameters=parse_qs(parts.query+'&'+parts.fragment)
            capi=parameters.get('capi',[''])[0].rstrip('/');host=urlsplit(capi)
            if host.scheme!='https' or not (host.hostname or '').endswith('-stage.contentmedia.eu') or host.port not in (None,443) or host.username or host.password or host.query or host.fragment:
                raise ValueError('CAPI_DEMO_AUTHORITY_UNBOUND')
            if parts.path.strip('/').split('/')[0] not in {'ecf3','ecf4'}:raise ValueError('CLIENT_FRAMEWORK_UNBOUND')
            name=parameters.get('gamename',[''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('GAME_RESOURCE_NAME_UNBOUND')
            for key,url in [('ecf',urljoin(response.url,'version.js')),('game',urljoin(response.url,'../'+name+'/version.js'))]:
                matches=re.findall(r'(?:ecf|game)_revision\s*=\s*["\']?(\d+)',get(url).text)
                if len(matches)!=1:raise ValueError('VERSION_UNBOUND')
                versions[key]=matches[0]
            base=capi+'/'+game.symbol+'/play';report.update(endpoint=base,versions=versions)
            cur=q.get('currency',['EUR'])[0]
            initial=exchange('init',{'opid':'44','extsession':str(time.time_ns()+secrets.randbelow(10000)),'cur':cur,'desktopmode':'true',
                'lang':q.get('language',['en_gb'])[0],'screenres':'1280,720,1280,720','extjur':'NA'})
            if not session:raise ValueError('SESSION_UNBOUND')
            quotes=declared_modes(initial);report['declaredModes']=[{'id':code} for code in quotes];balance=money(initial.findtext('player/balance'))
            level,cost=min(quotes['DEF'].items(),key=lambda pair:pair[1])
            delay=max(int(initial.findtext('gamesession/minspindelay') or '0'),int(initial.findtext('.//spin/mindelay') or '0'))/1000+.15
            for index in range(spins):
                if stop_event.wait(delay):break
                row={'id':'DEF','amount':str(cost),'betlevel':level,'balanceBefore':str(balance),'status':'dispatched'}
                report['rounds'].append(row);persist()
                paid=exchange('purchase',{'gamesession':session,'amount':str(cost),'cur':cur,'bmode':'DEF','betdetails':'','betlevel':level,
                    'pmode':'click-s0','orientation':'landscape','sound':'bgeffect','monetaryunit':'money','gamespeed':'normal'})
                info=paid.find('roundinfo');roundid=paid.findtext('roundid')
                if info is None or not roundid:raise ValueError('ROUND_IDENTITY_UNBOUND')
                public=ET.fromstring(paid.findtext('game/pubdata'))
                if any(n.tag.upper() in {'CHOICE','SELECT','OPTIONS','PICK'} for n in public.iter()):raise ValueError('CHOICE_CONTINUATION_UNBOUND')
                ack=exchange('checkwin',{'roundid':roundid,'gamesession':session})
                after=money(ack.findtext('player/balance'));win=money(info.findtext('winamount'))
                if ack.findtext('roundid')!=roundid or after!=balance-cost+win:raise ValueError('SETTLEMENT_MISMATCH')
                row.update(status='closed',win=str(win),balanceAfter=str(after));balance=after;persist()
                progress('ELK CAPI: base purchase + checkwin captured; strict offline verifier follows.')
        except Exception as exc:report['error']=type(exc).__name__+': '+str(exc) if isinstance(exc,ValueError) else type(exc).__name__+': bootstrap/transport failure'
        finally:client.close();persist()
        result=convert_case(game,capture,root/'tests'/(capture.name+'-verified'))
        result.requested_spins=spins
        if report.get('error'):result.error=report['error']+'; '+result.error
        result.failed_spins=max(0,spins-result.successful_spins)
        return result
