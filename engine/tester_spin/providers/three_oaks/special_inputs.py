"""Source-backed selector transforms and optional stake inputs; no title rules."""
import re
from .code_primitives import ID, block, canonical_source

def antebet_input_contract(source, data):
    source = canonical_source(source)
    if not (re.search(r'\.Events\.game\.ante_bet\(' + ID + r'\)',source)
            and '.anteBetButton.isActive' in source
            and re.search(r'getAnteBetCoef=function\(\)\{var '+ID+r'=this\._get\("settings.ante_bet",\[0\]\)\[0\];',source)):
        return None
    settings=(data or {}).get('settings',{})
    values=settings.get('ante_bet',[])
    coefficient=values[0] if isinstance(values,list) and values else settings.get('booster_prices',{}).get('1')
    if not isinstance(coefficient,(int,float)) or isinstance(coefficient,bool) or coefficient<=0:
        return None
    return {'antebet_ui_observed':True,'antebet_values':[coefficient], 'antebet_executable':False}

def transformed_purchase_inputs(source,data,middleware):
    if not middleware:
        return None
    available=(data or {}).get('context',{}).get('available_buy_bonus',[])
    if not isinstance(available,list) or not available or any(not isinstance(v,int) or isinstance(v,bool) for v in available):
        return None
    candidates=[]
    for match in re.finditer(r'function actBuyFeature\(('+ID+r')\)\{',source):
        argument=match[1];body=block(source,match.end()-1)
        if body is None:continue
        sent=re.search(r'\.controllers\.flow\.act\('+ID+r'(?:\.'+ID+r')*\.BUY_SPIN,('+ID+r')\)',body)
        if not sent:continue
        fields=dict(re.findall(re.escape(sent[1])+r'\.('+ID+r')=([^;]+);',body[:sent.start()]))
        if not {'bet_per_line','lines'}.issubset(fields):continue
        mapping={};params=list(middleware);line_source=None
        # The price getter explicitly translates a zero-based UI type to a
        # one-based server price key. Preserve the advertised logical mode IDs.
        price_shift=re.search(r'getBuyFeature(?:CostByType|Multiplier)=function\(('+ID+r')\)\{.{0,500}?return this\._get\("settings.buy_bonus_prices\."\.concat\(\1\+([0-9]+)\),null\)',source)
        if price_shift and 'getBuyFeatureMultiplier=function' in price_shift[0]:
            invoked=re.search(r'\.getBuyFeatureMultiplier\('+re.escape(argument)+r'\)',body[:sent.start()])
            definitions=re.findall(r'getBuyFeatureMultiplier=(?!=)',source)
            if not invoked or len(definitions)!=1:
                price_shift=None
        if set(fields)=={'bet_per_line','lines','selected_mode'} and fields['selected_mode']==argument and price_shift:
            offset=0 if (data or {}).get('settings',{}).get('buy_bonus_price') else int(price_shift[2])
            if not re.fullmatch(ID+r'(?:\.'+ID+r')*\.settingsLines\(\)\[0\]',fields['lines']):continue
            mapping={str(v):{'selected_mode':v-offset} for v in available if v-offset>=0}
            params.append('selected_mode');line_source='settings_lines_first'
        elif set(fields)=={'bet_per_line','lines','ante_bet','buy_spin_scatters_count'}:
            selector=re.fullmatch(re.escape(argument)+r'\+([0-9]+)',fields['buy_spin_scatters_count'])
            ante=re.fullmatch(ID+r'(?:\.'+ID+r')*\.anteBetButton\.isActive\?'+ID+r'(?:\.'+ID+r')*\.getAnteBetCoef\(\):0',fields['ante_bet'])
            if not selector or not ante or not re.fullmatch(ID+r'(?:\.'+ID+r')*\.betFactor\(\)\[0\]',fields['lines']):continue
            # Bind the UI type to the same server price key, not to an assumed
            # relationship between game family and number of scatters.
            price=re.search(r'getBuyFeatureCostByType=function\(('+ID+r')\)\{var '+ID+r'=this\._get\("settings.freespins_buying_price_by_scatters_count\."\.concat\(\1\+'+selector[1]+r'\),0\);if\(!'+ID+r'\)'+ID+r'=this\._get\("settings.buy_bonus_prices\."\.concat\(\1\),0\)',source)
            if not price:continue
            mapping={str(v):{'buy_spin_scatters_count':v+int(selector[1]),'ante_bet':0} for v in available}
            params+=['ante_bet','buy_spin_scatters_count'];line_source='bet_factor_first'
        else:continue
        if not re.fullmatch(ID+r'(?:\.'+ID+r')*\.get\("bet_per_line"\)',fields['bet_per_line']):continue
        modes=[v for v in available if str(v) in mapping]
        candidates.append({'purchase_ui_observed':True,'purchase_modes':modes,'purchase_ui_modes':modes,
                           'purchase_params':{str(v):params for v in modes},'purchase_wire_values':mapping,
                           'purchase_selector_type':'preserve','purchase_value_sources':{'lines':line_source}})
    return candidates[0] if candidates and all(c==candidates[0] for c in candidates) else None
