from __future__ import annotations
import json,threading,uuid,time
from pathlib import Path
from curl_cffi import requests
from tester_spin.models import GameTestResult,SpinAttempt,utc_now_iso
from tester_spin.providers.base import ProviderAdapter
from tester_spin.providers.repeat_purchase import POLICY,repeat_complete
from .catalog import CODE,CATALOG_URL,FEED_URL,games_from_rows
from .runtime import NolimitSession,Unlearned,declaration,RoundLedger,continuation,save,MONETARY,require_idle_initial_state
from tester_spin.providers.result_farm_contract import ProviderFarmSpec,build_result_farm_contract,validate_result_farm_contract

SPEC=ProviderFarmSpec(provider='nolimit_city',protocol_family='nolimit-city-rc4-lzw',
    bootstrap_strategy='nolimit-fanpage-new-demo',transport='websocket-rc4-lzw',
    terminal_contract={'type':'provider','name':'nolimit-settled-round','nextMode':'NORMAL','remaining_counter_contract':'one_explicit_zero_counter_all_other_present_counters_zero_no_pendingWin','features.available':{'modern':'empty_or_exact_initial_catalog_after_observation','batch_catalog':{'source':['declared_feature_catalog','declared_feature_options','declared_purchase_options','declared_feature_categories'],'match':'exact_full_domain_from_current_init_independent_of_money_dialect'},'legacy_freespin_category':{'available':['FREESPINS'],'required_fields':['featureBet','numberOfFreespinsPlayed','totalSpinWinnings','freespinTriggeredThisSpin','wasFeatureBuy','playedBetValue','accumulatedRoundWin','mode','nextMode','freespinsLeft'],'featureBet':'false_or_purchase_root'},'legacy_two_stage_enhanced_bet':'empty_or_exact_declared_catalog','source':'current_init_catalog_or_full_selectors_purchase_selectors_categories','legacy_required_fields':['thisSpinWinning','totalSpinWinnings','enhancedBet','featureName','firstStage','secondStage','secondStageFsLeft']}},
    mode_option_keys=('automatic_actions','settlement_observations','selector','server_type','stake','price_multiplier','request_shape','monetary_contract','declared_feature_options','declared_feature_categories','declared_purchase_options','choice_domains','response_profile','declared_feature_catalog','declared_game_modes','observation_contract','execution_blocker','declared_additional_types'),
    runtime_outputs=('key','extPlayerKey'),protocol_static={'verification_contract':'nolimit-city/verified-runtime/v1',
        'bootstrap_endpoint':'https://demo.nolimitcity.com/EjsFrontWeb/fs','operator':'FANPAGE_DEMO',
        'websocket_path':'/EjsGameWeb/ws/game','outbound_codec':'RC4_HEX_JSON','inbound_codec':'LZW_JSON',
        'protocol':'@nolimitcity/game-communication@0.4.1',
        'operation_contract':{'schema':'nolimit-city/operation-contract/v1','planner':'shared_live_and_corpus',
            'ack':'response_mode_equals_requested_phase_plus_choice_ack','money':'round_ledger_required',
            'client_source':'current_session_name_and_version_with_sha256','offline_ok_certified':False},
        'repeat_extra_purchase_policy':{'policy':POLICY,'funding':'current_server_quote_pending_round_prize','selection':'decline_once_then_accept_every_affordable_offer','completion':'ledger_verified_normal_settlement','interruption':'PENDING'},
        'free_spin_continuation':{'type':'zeroBet','bet':'0.00'},
        'selection_primitive':{'type':'zeroBet','bet':'0.00','playerInteraction':{'selectedIndex':'{choice:string}'}},
        'extra_spin_selection_primitive':{'type':'zeroBet','bet':'0.00','playerInteraction':{'playExtraSpin':'{choice:yes|no}'}},
        'literal_extra_spin_monetary_contract':{'fields':['playExtraSpin','extraSpin'],'wire_field':'one_unambiguous_current_client_dialect','domain':'client_declared_yes_no','price':'current_offer.extraSpinCost','funding':'pending_round_prize','accept':'exact_negative_quote_accumulated_debit_client_bound_return_counter_boolean_or_client_flagless_dialect','reject':'zero_delta_NORMAL_wallet_settlement_history_flag_may_persist_only_after_prior_extra','funded_continuation':'one_zeroBet_after_verified_debit','repeat':'redeclare_quote_each_offer'},
        'source_bound_automatic_observations':{'source':'current_client_sha256','payload':'exact_zero_stake_request_including_constant_signal_parameters','ack':'confirmed_entry_in_requested_phase','money':'round_ledger_still_required','context':'direct_fresh_demo_transport_required_for_UI_only_action_spins_exclusion','category':'continuation_not_purchase_or_antebet'},
        'native_paid_extra_return':{'schema':'nolimit-city/single-extra-freespin/v1','phase':'FREESPIN','counters':'regular_one_and_explicit_total_one','menu':'no_pending_decisions','receipt':'current_quote_exact_negative_step_and_accumulated_debit','priority':'explicit_server_target_remains_authoritative'},
        'client_remaining_counter':{'source':'same_client_owner_keypad_direct_or_parsed_model_counter_with_sha256','values':'finite_nonnegative_safe_integral_number','outer_total':'independent_nonnegative_integer','flat_getter':'exact_raw_field_or_nullish_zero_with_actual_raw_field_required','conflict':'canonical_counter_must_agree'},
        'settled_catalog_subset':{'scope':'terminal_observation_only','domain':'current_init_declared_purchase_subset','proof':'NORMAL_or_acknowledged_completed_phase_no_active_decision_zero_counters_and_reconciled_wallet','unknown_labels':'remain_unresolved'},
        'numeric_extra_spin_monetary_contract':{'field':'playerSelectedExtraSpin','wire_type':'current_client_literal','funding':'pending_round_prize','price':'previous.game.extraSpinCost','accept':'exact_negative_quote_and_wasExtraSpin_true_and_quoted_target','reject':'zero_delta_and_wasExtraSpin_false_and_NORMAL','funded_continuation':'one_zeroBet_after_verified_debit','settlement':'round_ledger_required'},
        'extra_spin_monetary_contract':{'price':'previous.game.extraSpinCost','funding':'accumulatedRoundWin',
            'yes_ack':'mode=EXTRA_SPIN,nextMode=FREESPIN,freespinsLeft=1,isExtraSpin=true,win=-quoted_price',
            'no_ack':'mode=EXTRA_SPIN,nextMode=NORMAL,win=0','settlement':'initial_balance-root_cost+net_accumulated_win'},
        'rows_response_contract':{'profile':'rows_freespin_and_collect/v1','purchase_type':'FREESPIN',
            'boost_type':'BOOSTED_BET_X_ROWS','boost_enable':'boostedBetExtraRows_and_allowedFeatureTypes',
            'boost_ack':'playedRowsInBase_above_three_or_featureBet_true_without_wasFeatureBuy',
            'step_win':'totalSpinWinnings','freespin_counter':'freespinPlayed','choice_ack':'playerSelection',
            'features_catalog':['FREESPIN'],'preset_pick':'purchase_with_positive_selection_and_featureBuyRows_equals_playedRowsInFS',
            'collect_request':{'type':'gambleBet','bet':'0.00','playerInteraction':{'gambleCollected':True}},
            'collect_ack':'previous_nextMode_GAMBLE_then_mode_GAMBLE_nextMode_NORMAL_gambleCollect_true_zero_step_win_unchanged_accumulated_win',
            'gamble_scope':'settlement_only_not_gamble_alternatives'},
        'selection_primitive_scope':'selectedIndex_only',
        'selection_primitives':{'playerSelectedExtraSpin':{'type':'zeroBet','bet':'0.00','playerInteraction':{'playerSelectedExtraSpin':'{choice:current_client_literal_type}'}},
            'selectedIndex':{'type':'zeroBet','bet':'0.00','playerInteraction':{'selectedIndex':'{choice:string}'}},
            'playExtraSpin':{'type':'zeroBet','bet':'0.00','playerInteraction':{'playExtraSpin':'{choice:yes|no}'}},
            'extraSpin':{'type':'zeroBet','bet':'0.00','playerInteraction':{'extraSpin':'{choice:yes|no}'}},
            'gambleCollected':{'type':'gambleBet','bet':'0.00','playerInteraction':{'gambleCollected':True}}},
        'bound_literal_button_selection':{'source':'CLIENT_BOUND_LITERAL_BUTTONS','binding':'current_phase_runner_view_constructor_literal_buttons_same_argument_sdk_forward','ack':'requested_phase_then_client_declared_target_and_finite_nonnegative_result_path','money':'ROUND_LEDGER','category':'nested_choice_not_commercial_purchase'},
        'bound_settlement_selection':{'source':'CLIENT_BOUND_SETTLEMENT_BUTTONS','binding':'current_phase_idle_panel_buttons_callbacks_literal_ids_zero_stake_sdk','availability':'current_root_selector_client_model_predicate','ack':'requested_phase_NORMAL_no_pending_counters_wallet_required','money':'ROUND_LEDGER','category':'nested_choice_not_commercial_purchase'},
        'choice_domain_source':'current_client_static_ids_or_server_array_with_client_verified_bounds',
        'response_aliases':{'boostedBet':'wasBoostedBet','boostedBetPlayed':'wasBoostedBet','enhancedBet':'wasBoostedBet_bool_or_nonnegative_enum','step_win':['thisSpinWinning','thisSpinWinnings','totalSpinWinnings'],'scope':'proven_monetary_response_signatures','wasExtraSpin':'boolean_extra_aliases_must_agree_true_requires_current_extra_contract'},
        'additional_zero_bet_modes':{'RESPIN':'positive_integer_respinsLeft','FREESPIN_MINIGAME':'positive_integer_freespinsLeft','scope':'operation_state_and_pending_counters_independent_of_money_dialect','FREESPIN_TRIGGER_or_COIN_SPIN':'proven_extra_signature_zero_freespins_no_extra_cost_no_extra_spin','avalanches':'pending_win_and_recorded_state_shape','avalanche_respins':'recorded_state_shape_zero_extra_cost_explicit_no_extra_spin','stacked_free_respin':'stackedSpinTriggered_and_positive_freespinsLeft'},
        'level_avalanche_profile':{'required_fields':['totalSpinWinnings','accumulatedRoundWin','playedBetValue','mode','nextMode','numberOfFreespinsPlayed','freespinsLeft','freespinTriggeredThisSpin','wasFeatureBuy','collapsedReel','collectedWinningSymbols','previousLevel','currentLevel','isRandomLevel'],
            'step_win':'totalSpinWinnings','modifier_ack':'no_boost_or_extra_fields_in_profile',
            'features':'empty_missing_available_or_active_phase_validated_against_current_purchase_domain',
            'automatic_modes':['AVALANCHE_NORMAL','AVALANCHE_FREESPIN','AVALANCHE_FREESPIN_SUPER'],
            'continuation':'zeroBet_only_with_pendingWin_true_positive_step_win_and_collapsed_reel'},
        'shared_observation_contract':{'schema':'independent-server-observations/v1',
            'declarations':'init.feature_table_allowed_selectors_prices_and_stakes_before_execution_known_role_preserved_when_execution_blocked',
            'fresh_idle':'init_ok_isRestoreState_false_both_modes_NORMAL_remainingFreeSpins_zero_no_pending_counters_or_flags',
            'catalog':'exact_init_features_available_is_catalog_not_permission_for_unknown_phase',
            'phase':'active_matches_proven_phase_family_or_init_game_modes_or_current_declared_purchase_root_observation_does_not_grant_action_permission',
            'explicit_step_aliases':['win','thisSpinWinning','thisSpinWinnings','thisAvalancheWinnings'],
            'total_only':'requires_current_request_total_matches_step_delta_or_accumulated_round_win_no_implicit_discount',
            'normal_root':'current_normalBet_exact_stake_and_no_extra_parameters_explicit_modifiers_not_true_cost_and_settlement_verified',
            'purchase_root':'wasFeatureBuy_true_or_missing_flag_with_featureBet_true_current_declared_purchase_selector_and_reconciled_surcharge_debit',
            'terminal':'NORMAL_one_explicit_zero_remaining_counter_all_present_counters_zero_no_pendingWin_no_unknown_menu',
            'remaining_counters':['remainingFreeSpins','game.freespinsLeft','game.respinsLeft','game.secondStageFsLeft'],
            'collect_primitive':{'type':'gambleBet','bet':'0.00','playerInteraction':{'gambleCollected':True}},
            'collect_scope':'client_proven_request_previous_GAMBLE_with_gambleOptions_and_false_gambleCollect_then_ack_true_zero_win_normal_settled_no_gamble_alternative_coverage',
            'client_bound_automatic_action':{'source':'current_version_client_flow_map_or_registered_controller_or_bound_idle_animation','request':{'type':'zeroBet','bet':'0.00'},'ack':'response.game.mode_equals_requested_phase','evidence':'automatic-action.json_with_client_sha256','positive_win_required':False,'paid_extra_spin':'requires_separate_choice_and_money_contract'},
            'unknown_action':'PARCIAL_with_local_evidence'},
        'request_identity_scope':'one_exchange_not_round','declaration_source':'init.game.featureBuyTimesBetValue'})


class NolimitCityProvider(ProviderAdapter):
    key='nolimit_city'
    display_name='Nolimit City'
    catalog_url=CATALOG_URL
    max_test_concurrency=1

    def __init__(self,data_root:Path):
        self.provider_root=Path(data_root)/'providers'/self.key
        self.provider_root.mkdir(parents=True,exist_ok=True)
        self.http=requests.Session(impersonate='chrome')
        self.set_catalog_authority(False,'Catálogo de demos afiliadas: sin autoridad de eliminación')

    def game_dir(self,game):
        if (game.provider!=self.key or not CODE.fullmatch(game.symbol)
                or game.slug!=game.symbol.casefold()):raise ValueError('Nolimit City: identidad inválida')
        path=self.provider_root/game.slug;path.mkdir(parents=True,exist_ok=True)
        return path

    def catalog_record_invalid_reason(self,game):
        try:
            parsed=games_from_rows([{'studio':'Nolimit City','code':game.symbol,'name':game.name,'url':game.url}])[0]
            if game.provider!=self.key or game.slug!=parsed.slug:return 'Nolimit City: identidad inconsistente'
        except ValueError:return 'Nolimit City: fila de catálogo inválida'
        return ''

    def crawl_catalog(self,*,stop_event:threading.Event,progress,max_pages=100,on_game=None):
        self.set_catalog_authority(False,'Feed oficial de demos sin autoridad para borrar juegos')
        if stop_event.is_set():return []
        snapshot=json.loads(Path(__file__).with_name('catalog.json').read_text(encoding='utf-8'))
        games=games_from_rows(snapshot['games'])
        source='snapshot oficial incluido'
        try:
            response=self.http.get(FEED_URL,timeout=30);response.raise_for_status()
            rows=response.json();live=games_from_rows(rows)
            merged={g.symbol:g for g in games};merged.update({g.symbol:g for g in live})
            games=list(merged.values());source=FEED_URL
            (self.provider_root/'catalog.raw.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc:
            progress(f'Nolimit City: usando catálogo oficial guardado ({type(exc).__name__}).')
        found=[]
        for game in sorted(games,key=lambda g:g.name.casefold()):
            if stop_event.is_set():break
            folder=self.game_dir(game)
            metadata={'provider':self.key,'slug':game.slug,'symbol':game.symbol,'name':game.name,
                      'public_url':game.url,'demo_url':game.url,'catalog_source':source,'catalog_updated_at':utc_now_iso()}
            (folder/'game.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            found.append(game)
            if on_game:on_game(game)
        progress(f'Nolimit City: {len(found)} demos cargadas.')
        return found

    def har_artifact_dir(self,game):
        path=self.game_dir(game)/'analysis';path.mkdir(exist_ok=True);return path

    def farm_contract_dir(self,game):return self.game_dir(game)

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        requested=max(1,int(spins))
        result=GameTestResult(self.key,game.slug,game.name,game.url,requested,0,requested,'PARCIAL',symbol=game.symbol)
        if stop_event.is_set():
            result.status='CANCELADO';result.error='Ejecución detenida';return result
        start=time.monotonic()
        folder=self.game_dir(game)/'tests'/(utc_now_iso().replace(':','').replace('+','_')+'-'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True);result.run_dir=str(folder)
        bootstrap=folder/'bootstrap';bootstrap.mkdir()
        session=NolimitSession()
        try:
            init=session.open(game,self.http,timeout_s,stop_event,bootstrap)
            result.discovered_modes,result.feature_domains=declaration(init,require_idle=False)
            require_idle_initial_state(init)
            before=init.get('balance')
            base=result.discovered_modes[0]
            jobs=[base]*requested+[m for m in result.discovered_modes[1:] if m['executable'] for _ in range(requested)]
            def run_round(mode,return_probe=False):
                nonlocal before
                if stop_event.is_set():raise Unlearned('Nolimit City: ejecución detenida')
                directory=folder/f'attempt-{len(result.attempts)+1:03d}';directory.mkdir()
                attempt=SpinAttempt(number=len(result.attempts)+1,ok=False,mode_id='RETURN_SPIN' if return_probe else mode['id'],
                    mode_kind=mode['kind'],symbol=game.symbol,endpoint='wss://demo.nolimitcity.com/EjsGameWeb/ws/game',artifact_dir=str(directory))
                result.attempts.append(attempt)
                begin=getattr(session,'begin_round',None)
                if begin:begin(mode['id'])
                ledger=RoundLedger(before,mode)
                content=mode['request_shape'].copy()
                try:
                    step=0;step_limit=500
                    while step<step_limit:
                        step+=1
                        if stop_event.is_set():raise Unlearned('Nolimit City: ejecución detenida')
                        save(directory/f'{step:03d}.request.json',{'content':content})
                        answer=session.exchange(content,directory)
                        from .runtime import sanitized
                        save(directory/f'{step:03d}.response.json',sanitized(answer))
                        attempt.wire_steps=step
                        previous_extra_cost=ledger.extra_cost
                        raw_game=answer.get('game') or {}
                        if ('win' not in raw_game or any(type(raw_game.get(field)) is float
                                for field in ('freespinsLeft','freespinsRemaining'))):
                            load_client=getattr(session,'_load_choice_client',None)
                            if load_client:load_client()
                        done=ledger.accept(answer,request=content,operation=getattr(session,'pending_contract',None),client_source=getattr(session,'choice_client',None))
                        if ledger.extra_cost>previous_extra_cost:step_limit=step+500
                        confirm=getattr(session,'confirm_pending_choice',None)
                        if confirm:confirm(answer)
                        save(directory/'ledger.json',ledger.proof())
                        if done:break
                        if hasattr(session,'next_command'):
                            content=session.next_command(ledger.last_answer,directory,mode['id'],mode,raw_answer=answer)
                            continue
                        try:
                            content=continuation(ledger.last_answer,raw_answer=answer,declared_options=mode['declared_feature_options'],declared_categories=mode['declared_feature_categories'],declared_purchase_options=mode['declared_purchase_options'],declared_catalog=mode.get('declared_feature_catalog'),declared_game_modes=mode.get('declared_game_modes',()))
                        except Unlearned:
                            choose=getattr(session,'choice_command',None)
                            if not choose:raise
                            content=choose(answer,directory,mode['id'])
                    else:raise Unlearned('Nolimit City: ronda excede el límite de continuaciones')
                    finish=getattr(session,'finish_round',None)
                    if finish:finish(mode['id'])
                    before=ledger.after
                    attempt.ok=attempt.terminal=True;attempt.status_code=200
                    observation=(ledger.last_answer.get('feature_observation') or {}).get('kind')
                    if observation=='SETTLED_CATALOG_SUBSET':
                        mode['settlement_observations']=sorted(set(mode.get('settlement_observations',[]))|{observation})
                    if not return_probe:
                        option='spin' if mode['kind']=='SPIN' else mode['selector']
                        mode.update(validated=True,observed=True,evidence_level='REMOTE_EXECUTION',execution_state='PROVEN_TERMINAL',monetary_contract=MONETARY)
                        mode['covered_options']=[option];mode['sample_counts'][option]=mode['sample_counts'].get(option,0)+1
                        if mode['kind']=='SPIN':result.successful_spins=min(requested,result.successful_spins+1)
                    return not ledger.had_feature
                except Exception as exc:
                    attempt.error=str(exc) if isinstance(exc,(ValueError,TimeoutError)) else type(exc).__name__
                    raise
            for mode in jobs:
                run_round(mode)
                sync=getattr(session,'sync_choices',None)
                if sync:
                    for _ in range(16):
                        if sync(mode):break
                        run_round(mode)
                    else:raise Unlearned('Nolimit City: elecciones declaradas sin cobertura completa')
                progress(f"Nolimit City {game.name}: {mode['id']} OK.")
            if all(m['validated'] for m in result.discovered_modes):
                consecutive=0
                for _ in range(8):
                    consecutive=consecutive+1 if run_round(base,True) else 0
                    if consecutive>=2:break
                result.structural_map['nolimit_return']={'schema':'nolimit-city/verified-runtime/v1',
                    'status':'CONFIRMED' if consecutive>=2 else 'PENDING','consecutive_base':consecutive}
                if consecutive>=2:
                    if getattr(session,'sync_choices',None) and not all(session.sync_choices(mode) for mode in result.discovered_modes):
                        raise Unlearned('Nolimit City: elecciones declaradas sin cobertura completa')
                    result.status='OK'
                else:result.error='Nolimit City: retorno al giro normal no demostrado'
            else:result.error='Nolimit City: categorías declaradas todavía sin primitiva aprendida'
        except Unlearned as exc:
            result.status='CANCELADO' if stop_event.is_set() else 'PARCIAL';result.error=str(exc)
        except Exception as exc:
            result.status='PARCIAL' if result.successful_spins else 'ERROR'
            result.error=str(exc) if isinstance(exc,(ValueError,TimeoutError)) else 'Nolimit City: '+type(exc).__name__+' en la conexión Demo'
            http_status=getattr(getattr(exc,'response',None),'status_code',None)
            if isinstance(http_status,int):result.error=f'Nolimit City: HTTP {http_status} en la conexión Demo'
        finally:
            sync=getattr(session,'sync_choices',None)
            if sync:
                for mode in result.discovered_modes:sync(mode)
            session.close()
            result.failed_spins=max(0,requested-result.successful_spins)
            result.finished_at=utc_now_iso();result.elapsed_ms=(time.monotonic()-start)*1000
            save(folder/'result.json',result.to_dict())
            metadata_path=self.game_dir(game)/'game.json'
            try:metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
            except (OSError,ValueError):metadata={}
            metadata.update(provider=self.key,symbol=game.symbol,slug=game.slug,name=game.name,public_url=game.url,
                discovered_modes=result.discovered_modes,feature_domains=result.feature_domains)
            save(metadata_path,metadata)
        if result.error:progress(result.error)
        return result

    def build_farm_contract(self,game,result):
        contract=build_result_farm_contract(game,result,self.game_dir(game),SPEC)
        proof=result.structural_map.get('nolimit_return',{})
        roots=[m for m in result.discovered_modes if m.get('kind') in {'SPIN','PURCHASE','FEATURE_SPIN'}]
        if (proof.get('schema')!='nolimit-city/verified-runtime/v1' or proof.get('status')!='CONFIRMED'
                or proof.get('consecutive_base',0)<2 or not roots or any(m.get('monetary_contract')!=MONETARY for m in roots)):
            contract['ready']=False;contract['unresolved'].append('NOLIMIT_CURRENT_MONEY_AND_RETURN_REQUIRED')
        if any(set(domain.get('options',[]))-set(domain.get('covered',[])) for mode in roots for domain in mode.get('choice_domains',[])):
            contract['ready']=False;contract['unresolved'].append('NOLIMIT_CHOICES_NOT_COVERED')
        if any((not repeat_complete(domain) or domain.get('request_field') in ('playExtraSpin','extraSpin','playerSelectedExtraSpin') and domain.get('repeat_purchase_policy')!=POLICY) for mode in roots for domain in mode.get('choice_domains',[])):
            contract['ready']=False;contract['unresolved'].append('NOLIMIT_REPEAT_PURCHASE_NOT_COMPLETE')
        return contract

    def validate_farm_contract(self,contract):
        errors=validate_result_farm_contract(contract,SPEC)
        static=(contract.get('protocol') or {}).get('static') or {}
        if any('SETTLED_CATALOG_SUBSET' in (m.get('options') or {}).get('settlement_observations',[]) for m in contract.get('modes',[])):
            if static.get('settled_catalog_subset')!=SPEC.protocol_static['settled_catalog_subset']:errors.append('NOLIMIT_SETTLED_CATALOG_SUBSET_REQUIRED')
        if any(d.get('source')=='CLIENT_BOUND_LITERAL_BUTTONS' for m in contract.get('modes',[]) for d in (m.get('options') or {}).get('choice_domains',[])):
            if static.get('bound_literal_button_selection')!=SPEC.protocol_static['bound_literal_button_selection']:errors.append('NOLIMIT_BOUND_LITERAL_BUTTON_SELECTION_REQUIRED')
        if any(d.get('remaining_counter_contract') for m in contract.get('modes',[]) for d in (m.get('options') or {}).get('choice_domains',[])):
            if static.get('client_remaining_counter')!=SPEC.protocol_static['client_remaining_counter']:errors.append('NOLIMIT_CLIENT_COUNTER_REQUIRED')
        if static.get('verification_contract')!='nolimit-city/verified-runtime/v1':errors.append('NOLIMIT_CURRENT_VERIFICATION_REQUIRED')
        if any((m.get('options') or {}).get('monetary_contract')!=MONETARY for m in contract.get('modes',[]) if m.get('kind') in {'SPIN','PURCHASE','FEATURE_SPIN'}):
            errors.append('NOLIMIT_CURRENT_MONEY_REQUIRED')
        if any((mode.get('options') or {}).get('automatic_actions') for mode in contract.get('modes',[])):
            if static.get('source_bound_automatic_observations')!=SPEC.protocol_static['source_bound_automatic_observations']:
                errors.append('NOLIMIT_AUTOMATIC_OBSERVATIONS_REQUIRED')
        if any((mode.get('options') or {}).get('choice_domains') for mode in contract.get('modes',[])):
            if static.get('selection_primitive')!=SPEC.protocol_static['selection_primitive']:
                errors.append('NOLIMIT_SELECTION_PRIMITIVE_REQUIRED')
        if any(domain.get('request_field') in ('playExtraSpin','extraSpin') for mode in contract.get('modes',[]) for domain in (mode.get('options') or {}).get('choice_domains',[])):
            for key in ('extra_spin_selection_primitive','extra_spin_monetary_contract'):
                if static.get(key)!=SPEC.protocol_static[key]:errors.append('NOLIMIT_EXTRA_SPIN_CONTRACT_REQUIRED')
        if any(set(domain.get('options',[]))-set(domain.get('covered',[])) for mode in contract.get('modes',[]) for domain in (mode.get('options') or {}).get('choice_domains',[])):
            errors.append('NOLIMIT_CHOICES_NOT_COVERED')
        if any(domain.get('source')=='CLIENT_QUOTED_LITERAL_EXTRA' for mode in contract.get('modes',[]) for domain in (mode.get('options') or {}).get('choice_domains',[])):
            if static.get('literal_extra_spin_monetary_contract')!=SPEC.protocol_static['literal_extra_spin_monetary_contract']:
                errors.append('NOLIMIT_LITERAL_EXTRA_SPIN_CONTRACT_REQUIRED')
        if any(domain.get('request_field')=='playerSelectedExtraSpin' for mode in contract.get('modes',[]) for domain in (mode.get('options') or {}).get('choice_domains',[])):
            if static.get('numeric_extra_spin_monetary_contract')!=SPEC.protocol_static['numeric_extra_spin_monetary_contract']:
                errors.append('NOLIMIT_NUMERIC_EXTRA_SPIN_CONTRACT_REQUIRED')
        if any((mode.get('options') or {}).get('response_profile')=='rows_freespin_and_collect/v1' for mode in contract.get('modes',[])):
            if static.get('rows_response_contract')!=SPEC.protocol_static['rows_response_contract']:
                errors.append('NOLIMIT_ROWS_AND_COLLECT_CONTRACT_REQUIRED')
        for mode in contract.get('modes',[]):
            for domain in (mode.get('options') or {}).get('choice_domains',[]):
                field=domain.get('request_field','selectedIndex')
                expected=SPEC.protocol_static['selection_primitives'].get(field)
                if expected is None or (static.get('selection_primitives') or {}).get(field)!=expected:
                    errors.append('NOLIMIT_CHOICE_FIELD_PRIMITIVE_REQUIRED')
        if any((mode.get('options') or {}).get('observation_contract')=='independent-server-observations/v1' for mode in contract.get('modes',[])):
            if static.get('shared_observation_contract')!=SPEC.protocol_static['shared_observation_contract']:
                errors.append('NOLIMIT_SHARED_OBSERVATION_CONTRACT_REQUIRED')
        domains=[domain for mode in contract.get('modes',[]) for domain in (mode.get('options') or {}).get('choice_domains',[])]
        if any(domain.get('native_return_contract') for domain in domains):
            if static.get('native_paid_extra_return')!=SPEC.protocol_static['native_paid_extra_return']:
                errors.append('NOLIMIT_NATIVE_EXTRA_RETURN_REQUIRED')
        if any(domain.get('source')=='CLIENT_BOUND_SETTLEMENT_BUTTONS' for domain in domains):
            if static.get('bound_settlement_selection')!=SPEC.protocol_static['bound_settlement_selection']:
                errors.append('NOLIMIT_BOUND_SETTLEMENT_SELECTION_REQUIRED')
        if any(not repeat_complete(domain) or domain.get('request_field') in ('playExtraSpin','extraSpin','playerSelectedExtraSpin') and domain.get('repeat_purchase_policy')!=POLICY for domain in domains):errors.append('NOLIMIT_REPEAT_PURCHASE_NOT_COMPLETE')
        if any(domain.get('repeat_purchase_policy')==POLICY for domain in domains):
            if static.get('repeat_extra_purchase_policy')!=SPEC.protocol_static['repeat_extra_purchase_policy']:
                errors.append('NOLIMIT_REPEAT_PURCHASE_POLICY_REQUIRED')
        return list(dict.fromkeys(errors))
