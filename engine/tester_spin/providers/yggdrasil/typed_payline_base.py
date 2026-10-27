"""Closed BaseGame/payline action DTO bound to the current BASIC cash stake.

Recognizes the complete evaluation cycle observed in Actions 40556151509.
Unknown counters, feature actions, extra modes, and unexplained money remain
unsupported.  The runtime still validates collect/settlement and requires two
independent ordinary rounds before confirming return to base.
"""
from decimal import InvalidOperation

from .protocol import command_values
from .supermeter import num
from .typed_actions import _action, _board


def _money(value, stake, currency):
    if not isinstance(value, dict) or set(value) != {'currency', 'amount', 'amountNormalizedToBet'}:
        return None
    if value['currency'] != currency:
        return None
    amount = num(value['amount'])
    return amount if num(value['amountNormalizedToBet']) * stake == amount else None


def _positions(values, board):
    if not isinstance(values, list) or not values or len(values) > len(board):
        return None
    result = []
    for value in values:
        if (not isinstance(value, dict) or set(value) != {'x', 'y'} or
                any(type(v) is not int for v in value.values())):
            return None
        coordinate = value['x'], value['y']
        if coordinate not in board or coordinate in result:
            return None
        result.append(coordinate)
    return result


def ordinary(bet, constraints):
    try:
        if not isinstance(constraints, dict) or type(bet['step']) is not int or bet['step'] != 1 or bet['status'] != 'RESULTED':
            return False
        stake = num(constraints['basic_amount'])
        currency = constraints['currency']
        if stake <= 0 or bet['betcurrency'] != currency or num(bet['betamount']) != stake or num(bet['wonamount']) != 0:
            return False
        bd, ed = bet['betdata'], bet['eventdata']
        if (not {'coin', 'cashBet', 'cmd', 'accWa', 'accC'} <= set(bd) <=
                {'coin', 'cashBet', 'cmd', 'accWa', 'accC', 'initialBalance', 'cmds'}):
            return False
        if (bd['cmd'] != 'BASE_SPIN' or num(bd['coin']) != stake or
                num(constraints['basic_coin']) != stake or num(bd['cashBet']) != stake or num(bd['accC']) != 0):
            return False
        if 'initialBalance' in bd:
            num(bd['initialBalance'])
        if set(ed) != {'accC', 'accWa', 'response', 'nextCmds'} or command_values(ed['nextCmds']) != ['C']:
            return False
        if 'cmds' in bd and command_values(bd['cmds']) != ['C']:
            return False
        response = ed['response']
        if set(response) != {'coinWin', 'cashWin', 'clientData'} or num(response['coinWin']) != 0 or num(ed['accC']) != 0:
            return False
        cd = response['clientData']
        if set(cd) != {'actions', 'isFinished'} or cd['isFinished'] is not True:
            return False
        actions = cd['actions']
        if not isinstance(actions, list) or not 5 <= len(actions) <= 260:
            return False
        if not _action(actions[0], 'PresentModeStart', {'modeName'}) or actions[0]['modeName'] != 'BaseGame':
            return False
        if not _action(actions[1], 'NewSpin', {'board'}):
            return False
        board = _board(actions[1]['board'])
        if board is None or not _action(actions[2], 'FeatureHappened', {'featureIdentifier'}) or actions[2]['featureIdentifier'] != 'spin':
            return False
        width = max(x for x, y in board) + 1
        index, wins, total = 3, 0, num(0)
        while index < len(actions) and actions[index].get('$type') == 'ActionGame_PresentPaylineWinCombination':
            action = actions[index]
            if not _action(action, 'PresentPaylineWinCombination', {'win', 'winningCells', 'payline'}):
                return False
            amount = _money(action['win'], stake, currency)
            line, cells = _positions(action['payline'], board), _positions(action['winningCells'], board)
            if (amount is None or amount <= 0 or line is None or cells is None or len(line) != width or
                    [x for x, y in line] != list(range(width)) or cells != line[:len(cells)]):
                return False
            total += amount
            wins += 1
            index += 1
        if wins:
            if index >= len(actions) or not _action(actions[index], 'PresentIntermediateWin', {'win', 'accumulatedRoundWin'}):
                return False
            if any(_money(actions[index][key], stake, currency) != total for key in ('win', 'accumulatedRoundWin')):
                return False
            index += 1
        if index >= len(actions) or not _action(actions[index], 'FeatureHappened', {'featureIdentifier'}) or actions[index]['featureIdentifier'] != 'winEvaluation':
            return False
        index += 1
        if index != len(actions) - 1 or not _action(actions[index], 'PresentModeWin', {'modeWin', 'accumulatedRoundWin'}):
            return False
        if any(_money(actions[index][key], stake, currency) != total for key in ('modeWin', 'accumulatedRoundWin')):
            return False
        return all(num(value) == total for value in (bd['accWa'], ed['accWa'], response['cashWin']))
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError, ArithmeticError):
        return False


def validate_collect(before, after, request, constraints):
    """Bind this family's zero-cost C receipt to its demonstrated cash total.

    Other families remain outside this profile.  A terminal flag cannot replace
    the credited wonamount/exactWon and accumulated cash checks.
    """
    if len(before.get('bets', [])) != 1 or not ordinary(before['bets'][0], constraints):
        return
    try:
        root = before['bets'][0]
        if (request['cmd'] != 'C' or before['wagerid'] != after['wagerid'] or
                not after['terminal'] or len(after['bets']) != 1):
            raise ValueError('invalid receipt')
        bet = after['bets'][0]
        bd, ed = bet['betdata'], bet['eventdata']
        amount = num(root['eventdata']['response']['cashWin'])
        if (bet['step'] != root['step'] + 1 or bet['status'] != 'RESULTED' or
                num(bet['betamount']) != 0 or bet['betcurrency'] != root['betcurrency'] or
                set(bd) != {'coin', 'cashBet', 'cmd', 'accWa', 'accC'} or bd['cmd'] != 'C' or
                num(bd['coin']) != num(root['betdata']['coin']) or num(bd['cashBet']) != num(root['betdata']['cashBet']) or
                num(bd['accC']) != 0 or set(ed) != {'exactWon'} or
                any(num(value) != amount for value in (bet['wonamount'], bd['accWa'], ed['exactWon']))):
            raise ValueError('invalid receipt')
        if 'prizes' in bet:
            prizes = bet['prizes']
            if prizes is None and amount == 0:
                return
            if not isinstance(prizes, list):
                raise ValueError('invalid cash prizes')
            paid, net = num(0), num(0)
            for prize in prizes:
                if (prize['type'] != 'FIXED' or prize['wonAspect'] != 'CASH' or
                        prize['woncurrency'] != root['betcurrency']):
                    raise ValueError('invalid cash prize')
                paid += num(prize['wonamount'])
                net += num(prize['netamount'])
            if paid != amount or net != amount:
                raise ValueError('invalid cash prize total')
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError, ArithmeticError):
        raise ValueError('Cash-normalized payline collect settlement mismatch') from None
