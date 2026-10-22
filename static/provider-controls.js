/* Same provider state and controls in Setup and Cave. Reads never launch work. */
(function () {
  'use strict';
  const labels = {claude:'Claude',chatgpt:'ChatGPT',gemini:'Gemini',grok:'Grok'};
  const request = async (path, body) => {
    const hdrs = body ? {'Content-Type':'application/json'} : {'Accept':'application/json'};
    try {
      const tok = (new URLSearchParams(location.search)).get('token') || localStorage.getItem('anchor_token') || '';
      if (tok) {
        try { localStorage.setItem('anchor_token', tok); } catch (_) {}
        hdrs['X-Anchor-Token'] = tok;
        hdrs['Authorization'] = 'Bearer ' + tok;
      }
    } catch (e) {}
    const response = await fetch(path, {method:body ? 'POST' : 'GET',credentials:'same-origin',cache:'no-store',
      headers:hdrs,body:body ? JSON.stringify(body) : undefined});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Host provider settings are unavailable');
    return data;
  };
  function option(select, value, text, disabled) {
    const element = document.createElement('option'); element.value=value; element.textContent=text; element.disabled=!!disabled; select.append(element);
  }
  function selected(data, family, identity) {
    return data.connections.find(c => c.id === (identity || data.preferences.accounts[family] || family+'-default'));
  }
  function capacityText(account) {
    if (!account) return 'Unknown · select an account';
    const allowance = account.allowance;
    if (!allowance.windows.length) return account.auth.replaceAll('_',' ')+' · allowance '+allowance.state+' · Not reported';
    return allowance.state+' · '+allowance.windows.map(w=>w.label+': '+Math.round(w.remaining_percent*10)/10+'% remaining'+(w.resets_at ? ' · resets '+new Date(w.resets_at*1000).toLocaleString() : ' · reset Not reported')).join(' · ');
  }
  function frontierName(account) {
    const sel = account && account.catalog && account.catalog.selection;
    if (!sel || !sel.model) return null;
    const base = sel.model === 'best' ? 'claude-fable-5-1 (best)' : sel.model;
    return sel.effort ? base + ' · ' + sel.effort : base;
  }
  function quality(selects, account, choice) {
    const model=selects.model, effort=selects.effort;
    model.disabled=effort.disabled=!account || !account.execution.ready;
    const fName=frontierName(account);
    model.replaceChildren(); option(model,'latest_supported', fName ? 'Current frontier ('+fName+')' : 'Current frontier');
    (account && account.catalog.state==='fresh' ? account.catalog.rows : []).forEach(row=>option(model,row.model,row.model));
    if(choice && !Array.from(model.options).some(o=>o.value===choice.model))option(model,choice.model,choice.model+' · unavailable',true);
    model.value=choice && choice.model || 'latest_supported'; if(!model.value)model.value='latest_supported';
    effort.replaceChildren();
    function efforts() {
      const prior=effort.value || choice && choice.effort || 'highest_supported'; effort.replaceChildren(); option(effort,'highest_supported','Maximum supported');
      const rows=account ? account.catalog.rows : [], id=model.value==='latest_supported' ? account && account.catalog.selection && account.catalog.selection.model : model.value;
      const row=rows.find(r=>r.model===id); if(row && account.catalog.state==='fresh')row.efforts.forEach(value=>option(effort,value,value));
      if(!Array.from(effort.options).some(o=>o.value===prior))option(effort,prior,prior+' · unavailable',true);
      effort.value=prior; if(!effort.value)effort.value='highest_supported';
    }
    efforts(); model.onchange=efforts;
  }
  function canVerifyOnApply(account) {
    // An empty process cache is an unchecked observation. Selection requests
    // the existing Apply action's passive verification; it grants no execution.
    const cap=account.capability || {};
    if(account.mode!=='subscription' || !cap.installed || account.auth!=='unknown' ||
       account.test!=='not_tested' || account.observed_at)return false;
    if(account.family==='gemini')return account.native_default && account.id==='gemini-default' &&
      (cap.state==='not_checked' || cap.execution===true);
    return account.family==='grok' && !account.native_default &&
      (cap.state==='not_checked' || cap.isolated===true && cap.execution===true);
  }
  function controls(data, prefix, onChange) {
    const family=document.getElementById(prefix+'family'), account=document.getElementById(prefix+'account'), model=document.getElementById(prefix+'model'), effort=document.getElementById(prefix+'effort');
    let draft=JSON.parse(JSON.stringify(data.preferences));
    family.replaceChildren(); Object.keys(labels).forEach(value=>option(family,value,labels[value])); family.value=draft.family || data.default_family;
    function accounts() {
      const f=family.value; account.replaceChildren(); data.connections.filter(c=>c.family===f).forEach(c=>{
        const unchecked=canVerifyOnApply(c);
        option(account,c.id,c.name+' · '+(c.mode==='api' ? 'API · execution unready' : c.execution.ready ? 'native subscription' : unchecked ? 'native status unchecked; Apply verifies' : 'execution unready'),
          c.mode==='api' || !c.execution.ready && !unchecked);
      });
      account.value=draft.accounts[f] || f+'-default'; if(!account.value)account.selectedIndex=0;
      qualities();
    }
    function qualities(){ const c=selected(data,family.value,account.value); quality({model,effort},c,draft.quality[family.value]); if(onChange)onChange(c); }
    family.onchange=accounts; account.onchange=qualities; accounts();
    return {get:()=>({...draft,family:family.value,accounts:{...draft.accounts,[family.value]:account.value},quality:{...draft.quality,[family.value]:{model:model.value,effort:effort.value}}})};
  }
  function fmtUsd(v) {
    const n = Number(v || 0);
    return '$' + n.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function fmtTokens(n) {
    const v = Number(n || 0);
    if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return Math.round(v).toLocaleString('en-US') + ' (' + (v / 1e3).toFixed(1) + 'k)';
    return v.toLocaleString('en-US');
  }
  window.AnchorProviders={request,labels,selected,capacityText,controls,fmtUsd,fmtTokens};
  if(!document.getElementById('cave-provider-controls')) return;
  let data, controller, opening=null, dialog;
  const gear=document.getElementById('setup-gear'), railHead=document.querySelector('.provider-rail-head'), title=document.querySelector('.masthead .mh-title');
  const narrow=matchMedia('(max-width:760px)');
  function placeGear(){(narrow.matches && title ? title : railHead).prepend(gear);}
  narrow.addEventListener('change',placeGear);placeGear();
  const message=document.getElementById('cave-provider-message');
  function ensureSummariesBox(){
    let summaries=document.getElementById('cave-account-summaries');
    if(!summaries){
      summaries=document.createElement('div');
      summaries.id='cave-account-summaries';
      summaries.setAttribute('aria-label','Named account usage');
      const ctrlBox=document.getElementById('cave-provider-controls');
      ctrlBox.prepend(summaries);
    }
    return summaries;
  }
  try {
    const bootBox = ensureSummariesBox();
    const cachedHtml = localStorage.getItem('anchor_cave_summaries_cache');
    if (cachedHtml) {
      bootBox.innerHTML = cachedHtml;
    } else {
      bootBox.innerHTML = '<div class="engine-rail-header"><span class="engine-rail-title">Subscriptions &amp; Frontier</span><span class="engine-rail-gear">Setup →</span></div>'
        + ['Claude','ChatGPT','Gemini','Grok'].map(n => '<div class="cave-account-summary is-ready"><div class="ec-top"><span class="ec-dot active"></span><strong class="ec-name">'+n+' ★</strong><span class="ec-mode">Sub</span></div></div>').join('');
    }
  } catch (_) {}
  function paint(value){
    if(data && value.settings_revision < data.settings_revision)return;
    const preferences=data && controller && value.settings_revision===data.settings_revision ? controller.get() : value.preferences;
    data=value;controller=controls({...data,preferences},'cave-',()=>{});
    const account=selected(data,data.preferences.family || data.default_family), cap=document.getElementById('cave-provider-capacity');
    cap.className='provider-capacity '+(account ? account.capacity : 'unknown');
    cap.querySelector('strong').textContent=account ? labels[account.family]+' · '+account.name : 'Provider capacity';
    cap.querySelector('span').textContent=capacityText(account)+(account && account.warning ? ' · '+account.warning : '');
    const summaries=ensureSummariesBox();
    summaries.replaceChildren();
    const hdr=document.createElement('div');
    hdr.className='engine-rail-header';
    hdr.innerHTML='<span class="engine-rail-title">Subscriptions &amp; Frontier</span><span class="engine-rail-gear">Setup →</span>';
    hdr.onclick=e=>open(e.currentTarget);
    summaries.append(hdr);
    const us = data.usage_summary && data.usage_summary.windows;
    const w7 = us && us['7d'], w30 = us && us['30d'];
    const monRoot = (data.usage_summary && data.usage_summary.allowance_monitor) || {};
    const monFamilies = monRoot.families || {};
    const autoSched = (monRoot.auto_refresh && monRoot.auto_refresh.schedule) || 'Allowance: every 15m · Models: Nightly (02:00 local)';
    hdr.title = 'Verified CLI frontier models & subscription allowances · ' + autoSched;
    if (w7 && w30) {
      const banner = document.createElement('div');
      banner.className = 'cave-usage-banner';
      banner.title = 'Allowance auto-refreshes every 15m during the workday (plus live on every CLI turn); Model frontier verified Nightly at 02:00 local (' + (monRoot.as_of || monRoot.updated_at || 'current') + ')';
      banner.innerHTML = '<strong>⚡ 7d: ~' + fmtUsd(w7.hypothetical_usd) + ' (' + fmtTokens(w7.total_tokens) + ')</strong><span>30d: ~' + fmtUsd(w30.hypothetical_usd) + ' · ↻ 15m / Nightly</span>';
      banner.onclick = e => open(e.currentTarget);
      summaries.append(banner);
    }
    data.connections.forEach(connection=>{
      const row=document.createElement('div');
      const isSelected=connection.id===(data.preferences.accounts[connection.family] || connection.family+'-default');
      const mon = monFamilies[connection.family] || {};
      const isDefaultSub = Boolean(connection.native_default && connection.mode==='subscription');
      const isReady=Boolean((connection.execution && connection.execution.ready) || (isDefaultSub && mon.connected));
      row.className='cave-account-summary'+(isSelected?' is-selected':'')+(isReady?' is-ready':'');
      row.dataset.accountId=connection.id;
      const fModel=frontierName(connection) || (isDefaultSub && mon.frontier_model) || null;
      const qChoice=data.preferences.quality[connection.family];
      const prefModel=qChoice && qChoice.model;
      const fam7 = w7 && w7.by_family && w7.by_family[connection.family];
      const fam30 = w30 && w30.by_family && w30.by_family[connection.family];
      const spend7Text = fam7 ? '~' + fmtUsd(fam7.hypothetical_usd) : '';
      const spend30Text = (fam7 || fam30) ? ' · 30d: ~' + fmtUsd(fam30 && fam30.hypothetical_usd) + ' (' + fmtTokens(fam30 ? fam30.total_tokens : 0) + ' tok)' : '';
      const modeBadge = connection.mode==='api' ? 'API' : 'Sub';

      let pctVal = null;
      if(connection.allowance && connection.allowance.windows && connection.allowance.windows.length){
        pctVal = Math.max(0,Math.min(100,Math.round(Number(connection.allowance.windows[0].remaining_percent||0))));
      } else if(isDefaultSub && typeof mon.remaining_percent === 'number'){
        pctVal = Math.max(0,Math.min(100,Math.round(Number(mon.remaining_percent))));
      }

      const topRow=document.createElement('div');
      topRow.className='ec-top';
      const dot=document.createElement('span');
      dot.className='ec-dot '+(isReady?'active':'idle');
      const heading=document.createElement('strong');
      heading.className='ec-name';
      const customNick = connection.name && connection.name !== 'Primary' && connection.name !== 'Existing native sign-in' && !connection.native_default;
      heading.textContent=labels[connection.family]+(customNick ? ' · '+connection.name : '')+(isSelected?' ★':'');
      const badge=document.createElement('span');
      badge.className='ec-mode';
      badge.textContent=modeBadge;
      topRow.append(dot,heading,badge);

      const rightTag = (isDefaultSub && mon.short_allowance) ? mon.short_allowance : (pctVal !== null ? (pctVal + '% left') : spend7Text);
      if(rightTag){
        const sp=document.createElement('span');
        sp.className='ec-spend'+(pctVal !== null && pctVal <= 20 ? ' is-low' : '');
        sp.textContent=rightTag;
        topRow.append(sp);
      }

      const shortDate = s => String(s || '').replace(/^[A-Za-z]{3}\s+/, '');
      const resetSuffix = (isDefaultSub && mon.reset_7d_text && mon.reset_5h_text)
        ? (' · rst ' + shortDate(mon.reset_5h_text) + ' / 7d ' + shortDate(mon.reset_7d_text).replace(/\s+\d{2}:\d{2}$/, ''))
        : (isDefaultSub && mon.primary_reset_text)
          ? (' · resets ' + shortDate(mon.primary_reset_text))
          : (spend7Text ? (' · 7d ' + spend7Text) : '');
      const modelTxt = (!prefModel || prefModel==='latest_supported')
        ? (fModel || 'unverified')
        : (prefModel + (fModel ? ' ('+fModel+')' : ''));
      const frontierLine=document.createElement('div');
      frontierLine.className='ec-frontier';
      frontierLine.textContent=modelTxt + resetSuffix;
      frontierLine.title='Frontier: ' + modelTxt + (isDefaultSub && mon.summary_line ? ' · ' + mon.summary_line : '');

      row.append(topRow,frontierLine);

      if(pctVal !== null){
        const barRow=document.createElement('div');
        barRow.className='ec-bar-row';
        const meter=document.createElement('div');
        meter.className='cave-mini-meter ec-bar';
        const fill=document.createElement('b');
        fill.style.width=pctVal+'%';
        if(pctVal<=20)fill.className='is-low';
        meter.append(fill);
        barRow.append(meter);
        row.append(barRow);
      }

      const details=document.createElement('span');
      details.className='ec-sub';
      const monBasis = (isDefaultSub && mon.basis_label && !(connection.allowance && connection.allowance.windows && connection.allowance.windows.length)) ? (' · ' + mon.basis_label) : '';
      details.textContent=capacityText(connection)+monBasis+' · '+(connection.anchor_observed.tokens===null?'observed usage unknown':connection.anchor_observed.tokens.toLocaleString()+' observed tokens · '+connection.anchor_observed.state)+spend30Text+(connection.mode==='api'?' · API cost '+connection.api_spend.state:'');
      row.append(details);

      row.onclick=e=>open(e.currentTarget);
      summaries.append(row);
    });
    try { localStorage.setItem('anchor_cave_summaries_cache', summaries.innerHTML); } catch (_) {}
  }
  async function load(){try{paint(await request('/api/provider-setup'));message.textContent='Apply affects new work; conversations keep their source.';}catch(error){message.textContent=error.message;}}
  function close(){if(dialog && dialog.open){dialog.close();if(opening)opening.focus();load();}}
  function open(from){
    opening=from;
    const b=(window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || Date.now();
    if(!dialog){dialog=document.createElement('dialog');dialog.className='provider-dialog';dialog.setAttribute('aria-label','Setup settings');const iframe=document.createElement('iframe');iframe.title='Anchor Setup settings';iframe.src='/setup?embed=1&v='+encodeURIComponent(b);dialog.append(iframe);document.body.append(dialog);dialog.addEventListener('cancel',()=>{if(opening)opening.focus();load();});}
    else dialog.querySelector('iframe').contentWindow.postMessage({type:'anchor-setup-open'},location.origin);
    dialog.showModal();
  }
  document.getElementById('setup-gear').addEventListener('click',e=>open(e.currentTarget));
  document.getElementById('cave-provider-capacity').addEventListener('click',e=>open(e.currentTarget));
  document.getElementById('cave-provider-settings').addEventListener('click',e=>open(e.currentTarget));
  document.getElementById('cave-provider-apply').addEventListener('click',async()=>{
    if(!controller)return;try{paint(await request('/api/provider-setup/apply',{preferences:controller.get(),expected_revision:data.settings_revision}));message.textContent='Saved for new work. Existing conversations retain their source.';}catch(error){message.textContent=error.message;}
  });
  window.addEventListener('message',event=>{if(event.origin!==location.origin || !dialog || event.source!==dialog.querySelector('iframe').contentWindow)return;if(event.data && event.data.type==='anchor-setup-close')close();if(event.data && event.data.type==='anchor-setup-saved')load();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  setInterval(()=>{if(!document.hidden)load();},60000);load();
})();
