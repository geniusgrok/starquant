import sys,json,hashlib,subprocess,datetime as dt,bisect
from pathlib import Path
import numpy as np
STAR=Path('/workspace/starquant'); COIN=Path('/workspace/coinquant');sys.path[:0]=[str(STAR),str(COIN)]
from btc_perp.config import load_config
from btc_perp.measure import _prepare
from scripts.frontier import initial_state,resume,_channels
from research.session_market import WARMUP_TRADE
from research import session_schedule
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
iso=lambda ms:dt.datetime.fromtimestamp(int(ms)/1000,dt.timezone.utc).isoformat()
original=json.loads((STAR/'reports/btc_account_causal.json').read_text()); shared=json.loads((COIN/'evidence/third-round-20261001/accounts.json').read_text())
identity={'star_head':subprocess.check_output(['git','-C',str(STAR),'rev-parse','HEAD'],text=True).strip(),'coin_head':subprocess.check_output(['git','-C',str(COIN),'rev-parse','HEAD'],text=True).strip(),'script_sha256':sha(__file__),'causal_report_sha256':sha(STAR/'reports/btc_account_causal.json'),'shared_accounts_sha256':sha(COIN/'evidence/third-round-20261001/accounts.json'),'causal_recorded_head':original['provenance']['git_head'],'shared_sources':shared['sources'],'kernel_source_matches_causal_report':{k:sha(STAR/k)==v for k,v in original['provenance']['files_sha256'].items()},'inputs':{k:sha(STAR/'data'/k) for k in original['inputs']}}
assert all(v for k,v in identity['kernel_source_matches_causal_report'].items() if k != 'btc_perp/robustness.py')
assert identity['inputs']==original['inputs']
identity['warmup_trade_sha256']=sha(COIN/WARMUP_TRADE)
assert identity['warmup_trade_sha256']==shared['market_identity']['warmup_trade_sha256']
identity['schedule_sha256']=session_schedule.load()['primary']['sha256']
assert identity['schedule_sha256']==shared['schedule_sha256']
identity['kernel_module_hashes']={k:sha(STAR/k) for k in ('scripts/frontier.py','btc_perp/measure.py','btc_perp/costs.py','btc_perp/config.py','config/btc_account.yaml')}
cfg=load_config(); n=90*1440
arrays=tuple(np.ascontiguousarray(a[:n]) for a in _prepare(cfg));o,h,low,c,qv,fund,fx,days,minute,hh,ll,xh,xl,gate=arrays
start=1577836800000; ts=start+np.arange(n)*60000
starts=np.array(session_schedule.load()['primary']['starts_ms'],dtype=np.int64)
# Entry/add signal availability only: other kernel decisions remain continuous.
allowed=np.zeros(n,dtype=bool)
for s in starts:
 allowed |= (ts+60000>=s)&(ts+60000<s+300000)
w=json.loads((COIN/WARMUP_TRADE).read_text());wh=np.array([float(r[2]) for r in w]);wl=np.array([float(r[3]) for r in w]);nh=n//60
WH,WL,WXH,WXL=_channels(np.r_[wh,h.reshape(nh,60).max(1)],np.r_[wl,low.reshape(nh,60).min(1)],cfg.entry_hours,cfg.exit_hours)
WH,WL,WXH,WXL=[np.repeat(a[len(w):],60) for a in (WH,WL,WXH,WXL)]
runs={}; saved={'ts':ts}
for name,g,fee in [('continuous_recorded_kernel',gate,0),('entry_add_gate_only_795_schedule',gate*allowed,0),('taker_fee_only_0.00075',gate,0.00075),('december_warmup_only',gate,0)]:
 state=initial_state(float(fx[0]));state[23]=fee;eq=np.empty(n);trace=np.zeros((n,5))
 channels=(WH,WL,WXH,WXL) if name=='december_warmup_only' else (hh,ll,xh,xl)
 result=resume(state,0,n,o,h,low,c,fund,fx,*channels,cfg.stop,cfg.trail,cfg.add_step,cfg.max_units,cfg.risk,cfg.dd_flat,cfg.iso_frac,cfg.cooldown_hours*60,cfg.ratchet_gain,cfg.ratchet_trail,cfg.heat,cfg.flatten_ratio,cfg.entry_scale_below,cfg.entry_scale,g,qv,eq,trace,1)
 changed=np.flatnonzero(np.any(trace[:,[0,1,4]]!=np.vstack([np.zeros((1,3)),trace[:-1,[0,1,4]]]),axis=1))
 events=[{'minute_index':int(i),'bar_open_ms':int(ts[i]),'bar_open_utc':iso(ts[i]),'side':float(trace[i,0]),'qty':float(trace[i,1]),'entry':float(trace[i,4]),'wallet':float(trace[i,3]),'equity_cny_close':float(eq[i])} for i in changed]
 runs[name]={'window_start':iso(start),'end_exclusive':iso(start+n*60000),'final_cny':float(result[0]),'min_equity_over_peak':float(result[1]),'long_entries':int(result[2]),'short_entries':int(result[3]),'stops':int(result[4]),'initial_wallet':float(initial_state(float(fx[0]))[0]),'first_equity_cny':float(eq[0]),'events':events,'state':state.tolist()}
 saved[name+'_trace']=trace;saved[name+'_equity']=eq
np.savez_compressed('/tmp/btc-complete-star-diagnosis-traces.npz',**saved)
# Earliest threshold signal with and without the shared December hourly warmup.
w=json.loads((COIN/WARMUP_TRADE).read_text());wh=np.array([float(r[2]) for r in w]);wl=np.array([float(r[3]) for r in w]);nh=n//60
HH,LL,_,_=_channels(np.r_[wh,h.reshape(nh,60).max(1)],np.r_[wl,low.reshape(nh,60).min(1)],cfg.entry_hours,cfg.exit_hours)
HH=np.repeat(HH[len(w):],60);LL=np.repeat(LL[len(w):],60)
signals={}
for name,upper,lower in [('original_no_pre2020_warmup',hh,ll),('shared_december_warmup_thresholds',HH,LL)]:
 ix=np.flatnonzero((gate>0)&((c>upper)|(c<lower)))
 first=int(ix[0]);t=int(ts[first]+60000);idx=bisect.bisect_right(starts.tolist(),t)-1
 signals[name]={'signal_close_utc':iso(t),'signal_close_ms':t,'close':float(c[first]),'entry_high':float(upper[first]),'entry_low':float(lower[first]),'side':1 if c[first]>upper[first] else -1,'attended_at_signal':bool(allowed[first]),'preceding_start_utc':iso(starts[idx]),'following_start_utc':iso(starts[idx+1]),'count_first90days':len(ix),'first_attended_threshold':None if not len(ix[allowed[ix]]) else {'signal_close_utc':iso(ts[ix[allowed[ix]][0]]+60000),'close':float(c[ix[allowed[ix]][0]]),'upper':float(upper[ix[allowed[ix]][0]]),'lower':float(lower[ix[allowed[ix]][0]])}}
row=shared['results']['Starquant-baseline'];sessions=row['sessions'];sent=[]
for ss in sessions:
 for cycle_idx,cy in enumerate(ss['cycles']):
  if cy['sent']:sent.append({'session_index':ss['index'],'start_ms':ss['start_ms'],'start_utc':iso(ss['start_ms']),'cycle_index':cycle_idx,'report':cy})
raw={'identity':identity,'scope':'90-day historical kernel diagnostics, not a full account nor a finite actual-runner counterfactual','one_factor_caveat':'schedule diagnostic masks only entry/add gate; continuous trailing/channel/risk kernel remains active; fee diagnostic changes only kernel taker fee','runs':runs,'first_threshold_signals':signals,'shared_first_sent_cycles':sent[:3],'shared_early_daily_cny':[{'date':iso(day*86400000),'equity_cny':value} for day,value in row['daily_cny'] if day*86400000 in (1581379200000,1581465600000,1585612800000)],'shared_first_trades':row['trades'][:12],'shared_all_trade_times':[iso(t['time']) for t in row['trades']],'shared_initial_daily_cny':row['daily_cny'][:3],'shared_fees':row['fees'],'shared_funding':row['funding'],'trace_artifact_sha256':sha('/tmp/btc-complete-star-diagnosis-traces.npz')}
Path('/tmp/btc-complete-star-diagnosis-raw.json').write_text(json.dumps(raw,indent=2)+'\n')
print(json.dumps({'first_threshold_signals':signals,'runs':{k:{kk:vv for kk,vv in v.items() if kk not in ('events','state')} for k,v in runs.items()},'first_events':{k:v['events'][:2] for k,v in runs.items()},'first_shared_sent':sent[:1]},indent=2))
