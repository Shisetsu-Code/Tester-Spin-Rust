"""Keep the signed KA client metadata consistent with its HTTP User-Agent."""
import re


def current_client_identity(user_agent=None, *, browser_profile=None):
    if isinstance(user_agent,str) and len(user_agent)<=1024 and '\r' not in user_agent and '\n' not in user_agent:
        match=re.search(r'\bChrome/([0-9]{2,4}(?:\.[0-9]+){3})\b',user_agent)
        if match and 'Windows NT' in user_agent:
            return user_agent,{'dt':'Chrome','dv':match[1],'do':'Windows'}
    if browser_profile is None:
        from curl_cffi.requests.impersonate import DEFAULT_CHROME
        browser_profile=DEFAULT_CHROME
    match=re.fullmatch(r'chrome([1-9][0-9]{1,3})(?:a)?',str(browser_profile))
    if not match:
        raise ValueError('KA: perfil HTTP Chrome no reconocido; no se firma un contexto adivinado')
    version=match[1]+'.0.0.0'
    user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/'+version+' Safari/537.36')
    return user_agent,{'dt':'Chrome','dv':version,'do':'Windows'}
