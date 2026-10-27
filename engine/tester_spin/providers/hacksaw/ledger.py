"""Current server quote and integer money conservation for a single Demo round."""
from decimal import Decimal, InvalidOperation
from .runtime import BONUS_ID, terminal

def integer(value, *, positive=False):
    if isinstance(value,bool) or value is None:
        raise ValueError('Hacksaw: importe ausente o booleano')
    try: result=Decimal(str(value))
    except InvalidOperation: raise ValueError('Hacksaw: importe inválido')
    if not result.is_finite() or result!=result.to_integral_value() or result<0 or (positive and result==0):
        raise ValueError('Hacksaw: importe no entero o fuera de dominio')
    return result

def balance(data,currency):
    account=data.get('accountBalance')
    if not isinstance(account,dict) or account.get('currencyCode')!=currency:
        raise ValueError('Hacksaw: moneda del saldo distinta o ausente')
    return integer(account.get('balance'))

def validate_declaration(data):
    bonuses=data.get('bonusGames')
    if not isinstance(bonuses,list):raise ValueError('Hacksaw: dominio bonusGames incompleto')
    seen=set()
    for item in bonuses:
        if not isinstance(item,dict):raise ValueError('Hacksaw: opción inválida')
        key=item.get('bonusGameId')
        if isinstance(key,bool) or not isinstance(key,(str,int)) or not BONUS_ID.fullmatch(str(key)) or str(key) in seen:
            raise ValueError('Hacksaw: selector inválido o duplicado')
        seen.add(str(key))
        try: factor=Decimal(str(item.get('betCostMultiplier')))
        except InvalidOperation:raise ValueError('Hacksaw: precio de opción inválido')
        if isinstance(item.get('betCostMultiplier'),bool) or not factor.is_finite() or factor<=0:
            raise ValueError('Hacksaw: precio de opción no demostrado')

class RoundLedger:
    def __init__(self,before,currency,stake,factor):
        self.before=integer(before)
        self.currency=currency
        try: multiplier=Decimal(str(factor))
        except InvalidOperation:raise ValueError('Hacksaw: multiplicador inválido')
        if isinstance(factor,bool) or not multiplier.is_finite() or multiplier<=0:
            raise ValueError('Hacksaw: multiplicador inválido')
        self.cost=integer(integer(stake,positive=True)*multiplier,positive=True)
        if self.cost>self.before:raise ValueError('Hacksaw: saldo Demo insuficiente')
        self.win=Decimal(0);self.round_id=None;self.closed=False;self.steps=0;self.after=None;self.balance_observations=0

    def accept(self,data):
        if self.closed:raise ValueError('Hacksaw: respuesta después del cierre')
        if type(data.get('statusCode')) is not int or data['statusCode']!=0:
            raise ValueError('Hacksaw: respuesta sin acuse exitoso')
        rd=data.get('round')
        if not isinstance(rd,dict) or not isinstance(rd.get('roundId'),str) or not rd['roundId']:
            raise ValueError('Hacksaw: identidad de ronda ausente')
        if self.round_id is not None and self.round_id!=rd['roundId']:
            raise ValueError('Hacksaw: continuación cambió de ronda')
        self.round_id=rd['roundId']
        if rd.get('status') not in {'started','wfwpc','completed'} or not isinstance(rd.get('possibleActions'),list):
            raise ValueError('Hacksaw: estado de ronda desconocido')
        if rd.get('status') in {'completed','wfwpc'} and rd['possibleActions']:
            raise ValueError('Hacksaw: controles pendientes en estado final')
        if any(data.get(k) is not None for k in ('promotionWin','offer','freeRoundOffer')) or rd.get('jackpotWin') is not None:
            raise ValueError('Hacksaw: promoción o jackpot sin contrato monetario')
        events=rd.get('events')
        if not isinstance(events,list):raise ValueError('Hacksaw: eventos monetarios ausentes')
        for event in events:
            if not isinstance(event,dict):raise ValueError('Hacksaw: evento inválido')
            if any(integer(event.get(k))!=0 for k in ('ba','bc','wc','awc')):
                raise ValueError('Hacksaw: cargo o crédito auxiliar no explicado')
            self.win+=integer(event.get('wa'))
            if integer(event.get('awa'))!=self.win:
                raise ValueError('Hacksaw: pago acumulado incoherente')
        self.closed=terminal(data)
        expected=self.before-self.cost+(self.win if self.closed else Decimal(0))
        if data.get('accountBalance') is None and self.steps>0 and not self.closed:
            # The official choice client requests updateBalance=false. Defer
            # settlement evidence; never invent an observed intermediate balance.
            pass
        else:
            self.after=balance(data,self.currency)
            self.balance_observations+=1
            if self.after!=expected:
                raise ValueError('Hacksaw: débito, continuación o liquidación no cuadra con el precio declarado')
        self.steps+=1

    def proof(self):
        return {'schema':'hacksaw/round-ledger/v1','currency':self.currency,'balance_before':str(self.before),
                'paid_cost':str(self.cost),'win':str(self.win),'balance_after':str(self.after),
                'round_id':self.round_id,'steps':self.steps,'balance_observations':self.balance_observations,'closed':self.closed}
