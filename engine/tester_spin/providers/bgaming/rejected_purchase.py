"""Bounded same-session diagnostic after an explicit purchase rejection."""
from pathlib import Path
from tester_spin.provider_return_checks import bgaming_check, save_exchange
from tester_spin.providers.bgaming.runtime import balance_total, provider_error_envelope
from tester_spin.return_to_base import pending_return


def probe_rejected_purchase(init, send, options, directory, stop_event):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    response, request, data=init()
    save_exchange(directory, request, data, 0)
    flow=data.get('flow') or {}
    if (response.status_code >= 400 or provider_error_envelope(data) is not None
        or data.get('error') or flow.get('state') not in {'ready','closed'}
        or 'spin' not in (flow.get('available_actions') or [])):
        return pending_return(directory,'La sesión no autoriza una tirada normal después del rechazo')
    return bgaming_check(send,options,directory,stop_event,initial_balance=balance_total(data))
