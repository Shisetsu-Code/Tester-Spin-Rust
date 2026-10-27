"""Shared policy for an independently quoted optional purchase.

Adapters supply the proven choices and funding pool. This module never guesses
wire commands, prices, categories, or whether a wallet can fund a purchase.
"""
from decimal import Decimal

POLICY='ACCEPT_UNTIL_UNAVAILABLE'


def funded_domain(domain,price,balance,*,accept,decline,funding_source):
    price=Decimal(str(price));balance=Decimal(str(balance))
    if not price.is_finite() or not balance.is_finite() or price<=0 or balance<0:
        raise ValueError('Cotización o fondos fuera de dominio')
    if not all(any(type(v) is type(option) and v==option for option in domain['options']) for v in (accept,decline)):
        raise ValueError('Decisiones fuera del dominio declarado')
    return {**domain,'available':list(domain['options']) if balance>=price else [decline],
        'accept_option':accept,'decline_option':decline,'quoted_price':str(price),
        'funding_balance':str(balance),'funding_source':funding_source,'repeat_purchase_policy':POLICY}


def choose_repeat(domain,covered):
    accept=domain['accept_option'];decline=domain['decline_option']
    if accept not in domain['available']:return decline,'INSUFFICIENT_PENDING_PRIZE'
    if decline not in covered:return decline,'COVER_DECLINE'
    return accept,'ACCEPT_AFFORDABLE'


def new_probe():
    return {'policy':POLICY,'status':'PENDING','accepted_purchases':0,'spent':'0',
        'terminal_reason':None,'funding_source':'ACCUMULATED_ROUND_WIN'}


def repeat_complete(domain):
    if domain.get('repeat_purchase_policy')!=POLICY:return True
    return (domain.get('repeat_purchase_probe') or {}).get('status')=='COMPLETE'
