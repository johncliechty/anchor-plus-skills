(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const CANONICAL_REPO='https://github.com/johncliechty/ghostworldlabs-anchor';
  const EMAIL_PROVIDERS={
    'gmail.com':{family:'gmail',label:'Primary Gmail & Calendar',imap_host:'imap.gmail.com',imap_port:993,app_pwd_url:'https://myaccount.google.com/apppasswords',provider_name:'Google / Gmail',verified:true},
    'googlemail.com':{family:'gmail',label:'Primary Gmail & Calendar',imap_host:'imap.gmail.com',imap_port:993,app_pwd_url:'https://myaccount.google.com/apppasswords',provider_name:'Google / Gmail',verified:true},
    'outlook.com':{family:'outlook',label:'Microsoft Outlook & Calendar',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Tip: 1-Click Windows Outlook works without a password if Outlook is open.'},
    'hotmail.com':{family:'outlook',label:'Microsoft Hotmail / Outlook',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Tip: 1-Click Windows Outlook works without a password if Outlook is open.'},
    'live.com':{family:'outlook',label:'Microsoft Live / Outlook',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Tip: 1-Click Windows Outlook works without a password if Outlook is open.'},
    'msn.com':{family:'outlook',label:'Microsoft MSN / Outlook',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Tip: 1-Click Windows Outlook works without a password if Outlook is open.'},
    'yahoo.com':{family:'custom',label:'Yahoo Mail & Calendar',imap_host:'imap.mail.yahoo.com',imap_port:993,app_pwd_url:'https://login.yahoo.com/account/security',provider_name:'Yahoo Mail',verified:true},
    'ymail.com':{family:'custom',label:'Yahoo Mail & Calendar',imap_host:'imap.mail.yahoo.com',imap_port:993,app_pwd_url:'https://login.yahoo.com/account/security',provider_name:'Yahoo Mail',verified:true},
    'icloud.com':{family:'custom',label:'Apple iCloud Mail & Calendar',imap_host:'imap.mail.me.com',imap_port:993,app_pwd_url:'https://appleid.apple.com/account/manage',provider_name:'Apple iCloud',verified:true},
    'me.com':{family:'custom',label:'Apple iCloud Mail & Calendar',imap_host:'imap.mail.me.com',imap_port:993,app_pwd_url:'https://appleid.apple.com/account/manage',provider_name:'Apple iCloud',verified:true}
  };

  const PROVIDER_HELP={
    claude:{title:'Claude Code',cliLabel:'claude-code',connectLabel:'Connect Claude Code',hint:'Opens Anthropic CLI sign-in in your browser',needsKeyFirst:false,altKeyUrl:'https://console.anthropic.com/settings/keys',altKeyLabel:'Or use Anthropic API key'},
    gemini:{title:'Gemini / Antigravity',cliLabel:'gemini + agy',connectLabel:'Connect with Google',hint:'Opens Google sign-in (works with free Google accounts!)',needsKeyFirst:false,altKeyUrl:'https://aistudio.google.com/app/apikey',altKeyLabel:'Or paste free Google AI Studio key'},
    chatgpt:{title:'ChatGPT / Codex',cliLabel:'codex',connectLabel:'Connect Codex',hint:'Opens OpenAI Codex sign-in in your browser',needsKeyFirst:false,altKeyUrl:'https://platform.openai.com/api-keys',altKeyLabel:'Or use OpenAI API key'},
    grok:{title:'Grok (xAI)',cliLabel:'grok',connectLabel:'Get Key & Connect Grok',hint:'Uses an xAI API key from console.x.ai',needsKeyFirst:true,altKeyUrl:'https://console.x.ai',altKeyLabel:'Open console.x.ai key page ↗'}
  };

  let loginPollTimer=null;
  let userTouchedImapHost=false;

  async function postWizardAction(action,payload){
    const api=window.AnchorProviders;
    const isSb=Boolean(window.IS_SANDBOX);
    const sbId=window.SANDBOX_ID||'';
    const body=Object.assign({action},isSb?{sandbox:true,sandbox_id:sbId}:{},payload||{});
    if(api && typeof api.request==='function'){
      return await api.request('/api/onboard-wizard/action',body);
    }
    const r=await fetch('/api/onboard-wizard/action',{
      method:'POST',
      credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    return await r.json();
  }

  async function getWizardState(){
    const q=(window.IS_SANDBOX)?('?sandbox=1&sandbox_id='+encodeURIComponent(window.SANDBOX_ID||'')):'';
    const r=await fetch('/api/onboard-wizard/state'+q,{credentials:'same-origin'});
    return r.ok?await r.json():null;
  }

  /* -----------------------------------------------------------------------
   * 1. Dead-Simple 4-CLI Provider Cards + Unmistakable "🟢 Connected" Badge
   * --------------------------------------------------------------------- */
  function renderSimpleProviderCards(accountsMap,targetEl){
    if(!targetEl || !accountsMap)return;
    targetEl.replaceChildren();
    let connectedCount=0;
    ['claude','gemini','chatgpt','grok'].forEach(fam=>{
      const info=accountsMap[fam]||{};
      const meta=PROVIDER_HELP[fam]||{title:info.label||fam,cliLabel:fam,connectLabel:'Connect',hint:''};
      const isConnected=Boolean(info.connected || info.cli_authenticated);
      if(isConnected)connectedCount+=1;

      const card=document.createElement('div');
      card.dataset.simpleProviderCard=fam;
      card.style.cssText='padding:12px 14px;border-radius:10px;border:1px solid '+(isConnected?'rgba(16,185,129,0.55)':'rgba(255,255,255,0.12)')+';background:'+(isConnected?'rgba(6,78,59,0.22)':'#0c111b')+';display:flex;flex-direction:column;gap:8px;min-width:0';

      const top=document.createElement('div');
      top.style.cssText='display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap';
      const title=document.createElement('strong');
      title.style.fontSize='14px';
      title.textContent=meta.title;

      const badge=document.createElement('span');
      badge.dataset.providerConnBadge=fam;
      badge.className='w3-badge '+(isConnected?'w3-badge-emerald':'w3-badge-amber');
      badge.style.cssText=isConnected
        ? 'background:#065f46;color:#6ee7b7;border:1px solid #10b981;font-weight:700;padding:3px 9px;border-radius:999px;font-size:12px'
        : 'background:#1e293b;color:#cbd5e1;border:1px solid #475569;padding:3px 9px;border-radius:999px;font-size:12px';
      badge.textContent=isConnected?'🟢 Connected':'⚪ Not Connected';
      top.append(title,badge);

      const sub=document.createElement('div');
      sub.className='muted small';
      sub.style.fontSize='12px';
      sub.textContent=(info.cli_installed?('CLI installed ('+meta.cliLabel+')'):('CLI auto-installs on Connect ('+meta.cliLabel+')'))+' · '+(isConnected?'Ready to run':meta.hint);

      const keyWrap=document.createElement('div');
      keyWrap.style.cssText='display:'+(meta.needsKeyFirst && !isConnected?'flex':'none')+';gap:6px;flex-wrap:wrap';
      const keyInp=document.createElement('input');
      keyInp.type='password';
      keyInp.placeholder=fam==='gemini'?'Paste free AI Studio key':'Paste API key';
      keyInp.style.cssText='flex:1;min-width:120px;padding:6px 8px;font-size:12px;border-radius:6px;border:1px solid #334155;background:#090d16;color:#f8fafc';
      keyWrap.append(keyInp);

      const btnRow=document.createElement('div');
      btnRow.style.cssText='display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:auto';
      const btn=document.createElement('button');
      btn.type='button';
      btn.className=isConnected?'btn-mini btn':'btn-mini primary btn emerald';
      btn.style.cssText='padding:7px 12px;font-weight:700;border-radius:7px;cursor:pointer';
      btn.textContent=isConnected?'✓ Connected (Reconnect)':meta.connectLabel;
      btn.onclick=async()=>{
        const pasted=(keyInp.value||'').trim();
        await connectProviderSimple(fam,pasted,keyWrap,keyInp,btn);
      };
      btnRow.append(btn);

      if(!isConnected){
        const keyToggle=document.createElement('button');
        keyToggle.type='button';
        keyToggle.className='btn-mini btn';
        keyToggle.style.cssText='padding:5px 8px;font-size:11.5px;opacity:0.88;cursor:pointer';
        keyToggle.textContent=meta.needsKeyFirst?'Open console.x.ai ↗':'Use API Key';
        keyToggle.onclick=()=>{
          keyWrap.style.display='flex';
          if(meta.altKeyUrl)window.open(meta.altKeyUrl,'_blank','noopener,noreferrer');
          keyInp.focus();
        };
        btnRow.append(keyToggle);
      }

      card.append(top,sub,keyWrap,btnRow);
      targetEl.append(card);
    });

    const sumBadge=$('cli-browser-summary-badge');
    if(sumBadge){
      sumBadge.textContent=connectedCount>0?('🟢 '+connectedCount+'/4 Connected'):'Claude Code · Gemini / AGY · Codex · Grok';
      sumBadge.className='w3-badge '+(connectedCount>0?'w3-badge-emerald':'w3-badge-sky');
    }
  }

  function renderAllProviderStrips(accountsMap){
    if($('setup-browser-accounts-strip'))renderSimpleProviderCards(accountsMap,$('setup-browser-accounts-strip'));
    if($('browserAccountsBanner'))renderSimpleProviderCards(accountsMap,$('browserAccountsBanner'));
  }

  async function connectProviderSimple(fam,apiKey,keyWrap,keyInp,btn){
    const msg=$('setup-cli-browser-msg')||$('wizBanner');
    if(btn)btn.disabled=true;
    if(msg)msg.textContent='Connecting '+fam+'…';
    try{
      const res=await postWizardAction('connect_provider_simple',{family:fam,api_key:apiKey||''});
      if(res && res.needs_api_key){
        if(keyWrap)keyWrap.style.display='flex';
        if(res.login_url && !res.opened_on_host)window.open(res.login_url,'_blank','noopener,noreferrer');
        if(keyInp)keyInp.focus();
        if(msg)msg.textContent=res.message||'Paste your API key and click Connect.';
        return;
      }
      if(res && res.connected){
        if(msg)msg.textContent='🟢 '+(res.message||'Connected!');
        const st=await getWizardState();
        if(st && st.browser_accounts && st.browser_accounts.accounts)renderAllProviderStrips(st.browser_accounts.accounts);
        if($('provider-refresh'))$('provider-refresh').click();
        return;
      }
      if(msg)msg.textContent=res.message||('Approve sign-in in your browser — watching for connection…');
      clearInterval(loginPollTimer);
      let ticks=0;
      loginPollTimer=setInterval(async()=>{
        ticks+=1;
        const st=await getWizardState();
        const accts=st && st.browser_accounts && st.browser_accounts.accounts;
        if(accts){
          renderAllProviderStrips(accts);
          if(accts[fam] && (accts[fam].connected || accts[fam].cli_authenticated)){
            clearInterval(loginPollTimer);
            // Persist verified status once detected
            try{await postWizardAction('connect_provider_simple',{family:fam});}catch(_e){}
            if(msg)msg.textContent='🟢 Connected! '+accts[fam].label+' is ready.';
            if($('provider-refresh'))$('provider-refresh').click();
            return;
          }
        }
        if(ticks>=72)clearInterval(loginPollTimer);
      },2500);
    }catch(e){
      if(msg)msg.textContent='Connection error: '+e.message;
    }finally{
      if(btn)btn.disabled=false;
    }
  }

  /* -----------------------------------------------------------------------
   * 2. Dead-Simple Email & Calendar Connect + "🟢 Connected" Badge
   * --------------------------------------------------------------------- */
  function updateEmailBadge(emailStatus){
    const badge=$('simple-comms-status-badge');
    const railSmall=$('rail-status-comms');
    const ok=Boolean(emailStatus && emailStatus.connected);
    const lbl=ok?('🟢 '+(emailStatus.status_label||'Connected')):'⚪ Not Connected';
    if(badge){
      badge.textContent=lbl;
      badge.className='w3-badge '+(ok?'w3-badge-emerald':'w3-badge-amber');
    }
    if(railSmall && ok){
      railSmall.textContent='🟢 '+(emailStatus.primary_email||'Connected');
    }
  }

  function detectEmailDomainAndFill(emailStr){
    const raw=String(emailStr||'').trim().toLowerCase();
    const atIdx=raw.lastIndexOf('@');
    if(atIdx<1)return null;
    const dom=raw.slice(atIdx+1);
    const hit=EMAIL_PROVIDERS[dom] || {
      family:'custom',
      label:'Email & Calendar ('+dom+')',
      imap_host:'imap.'+dom,
      imap_port:993,
      app_pwd_url:'',
      provider_name:dom,
      verified:false,
      auth_hint:'Use your mail provider password or 1-Click Windows Outlook.'
    };
    if($('comms-family'))$('comms-family').value=hit.family;
    if($('comms-email') && !$('comms-email').value)$('comms-email').value=emailStr;
    if($('comms-label') && !$('comms-label').value)$('comms-label').value=hit.label;
    if($('comms-imap-host') && (!userTouchedImapHost || !$('comms-imap-host').value))$('comms-imap-host').value=hit.imap_host;
    if($('comms-imap-port') && !userTouchedImapHost)$('comms-imap-port').value=String(hit.imap_port);
    if($('btn-comms-open-provider-app-pwd'))$('btn-comms-open-provider-app-pwd').disabled=!hit.app_pwd_url;
    if($('comms-detected-provider-hint')){
      const prefix=hit.verified?'✓ ':'ℹ ';
      $('comms-detected-provider-hint').textContent=prefix+hit.provider_name+' ('+hit.imap_host+')';
    }
    return hit;
  }

  function mountWizardVariableStrength(box, vsState){
    if(!box || !vsState)return;
    const cfg=vsState.config||{top_effort:'highest',heavy:{model_steps_below:0,effort_steps_below:0},light:{model_steps_below:1,effort_steps_below:2},heavy_skills:['anvil','chekhov','aegis','superjump']};
    const skills=Array.isArray(vsState.skills)?vsState.skills:[];
    const draft={
      top_effort:cfg.top_effort||'highest',
      heavy:{model_steps_below:Number(cfg.heavy&&cfg.heavy.model_steps_below||0),effort_steps_below:Number(cfg.heavy&&cfg.heavy.effort_steps_below||0)},
      light:{model_steps_below:Number(cfg.light&&cfg.light.model_steps_below!==undefined?cfg.light.model_steps_below:1),effort_steps_below:Number(cfg.light&&cfg.light.effort_steps_below!==undefined?cfg.light.effort_steps_below:2)},
      heavy_skills:Array.isArray(cfg.heavy_skills)?[...cfg.heavy_skills]:['anvil','chekhov','aegis','superjump']
    };
    box.innerHTML=`
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
        <strong style="font-size:15px;color:#fde68a">⚡ Variable Strength — Choose What <code>Heavy</code> &amp; <code>Light</code> Mean for Skills</strong>
        <span class="pill" style="background:#451a03;color:#fde68a">Relative Steps Below Your Subscription Top Tier</span>
      </div>
      <p class="muted" style="margin:0 0 10px;font-size:12.5px">Anchor queries your signed-in subscriptions for their newest top-tier model and effort. Define <strong>Heavy</strong> and <strong>Light</strong> in steps below that ceiling, and click any skill below to set its default.</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:10px;margin-bottom:10px">
        <div>
          <label style="font-size:12px">Highest Effort Ceiling (0 Steps Below)</label>
          <select data-wvs="top_effort">
            <option value="highest">Auto Highest (Ultra / Max / XHigh / High)</option>
            <option value="ultra">Ultra</option>
            <option value="max">Max</option>
            <option value="xhigh">XHigh</option>
            <option value="high">High</option>
          </select>
        </div>
        <div>
          <label style="font-size:12px">⚡ Heavy (Model / Effort Steps Below Top)</label>
          <div style="display:flex;gap:6px">
            <select data-wvs="heavy_m"><option value="0">Top Tier (0)</option><option value="1">-1 Model</option><option value="2">-2 Model</option></select>
            <select data-wvs="heavy_e"><option value="0">Top Effort (0)</option><option value="1">-1 Effort (High)</option><option value="2">-2 Effort (Med)</option></select>
          </div>
        </div>
        <div>
          <label style="font-size:12px">🪶 Light / Standard (Model / Effort Steps Below Top)</label>
          <div style="display:flex;gap:6px">
            <select data-wvs="light_m"><option value="1">-1 Model (Default)</option><option value="2">-2 Model</option><option value="0">Top Tier (0)</option></select>
            <select data-wvs="light_e"><option value="2">-2 Effort (Med)</option><option value="1">-1 Effort (High)</option><option value="3">-3 Effort (Low)</option><option value="0">Top Effort (0)</option></select>
          </div>
        </div>
      </div>
      <div data-wvs-skills="1" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px"></div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button type="button" class="btn primary" data-wvs-save="1">✓ Save Heavy / Light &amp; Skill Defaults</button>
        <span class="muted" data-wvs-msg="1" style="font-size:12px"></span>
      </div>
    `;
    const q=sel=>box.querySelector(sel);
    q('[data-wvs="top_effort"]').value=draft.top_effort;
    q('[data-wvs="heavy_m"]').value=String(draft.heavy.model_steps_below);
    q('[data-wvs="heavy_e"]').value=String(draft.heavy.effort_steps_below);
    q('[data-wvs="light_m"]').value=String(draft.light.model_steps_below);
    q('[data-wvs="light_e"]').value=String(draft.light.effort_steps_below);
    const sWrap=q('[data-wvs-skills="1"]');
    function drawPills(){
      sWrap.replaceChildren();
      const hSet=new Set(draft.heavy_skills);
      skills.forEach(sk=>{
        const on=hSet.has(sk.id);
        const b=document.createElement('button');
        b.type='button';
        b.className='btn';
        b.style.cssText='padding:4px 9px;font-size:12px;border-radius:999px;border:1px solid '+(on?'#f59e0b':'#334155')+';background:'+(on?'rgba(245,158,11,0.16)':'#0b111d')+';color:'+(on?'#fde68a':'#cbd5e1');
        b.textContent=(on?'⚡ ':'🪶 ')+sk.label;
        b.onclick=()=>{
          if(hSet.has(sk.id))hSet.delete(sk.id);else hSet.add(sk.id);
          draft.heavy_skills=skills.filter(x=>hSet.has(x.id)).map(x=>x.id);
          drawPills();
        };
        sWrap.append(b);
      });
    }
    drawPills();
    q('[data-wvs-save="1"]').onclick=async()=>{
      draft.top_effort=q('[data-wvs="top_effort"]').value;
      draft.heavy={model_steps_below:Number(q('[data-wvs="heavy_m"]').value||0),effort_steps_below:Number(q('[data-wvs="heavy_e"]').value||0)};
      draft.light={model_steps_below:Number(q('[data-wvs="light_m"]').value||1),effort_steps_below:Number(q('[data-wvs="light_e"]').value||2)};
      const msg=q('[data-wvs-msg="1"]');
      msg.textContent='Saving…';
      try{
        const res=await postWizardAction('save_variable_strength',{variable_strength:draft});
        msg.textContent='✓ '+(res.message||'Saved Variable Strength settings!');
      }catch(e){msg.textContent='⚠ '+e.message;}
    };
  }

  /* -----------------------------------------------------------------------
   * 3. Hard-Drive Folder Checkmark Tree + Gandalf Drag-Merge / Split Workbench
   * --------------------------------------------------------------------- */
  function mountGandalfDriveWorkbench(container,initialDriveTree,initialProposals){
    if(!container || container.dataset.mounted==='1')return;
    container.dataset.mounted='1';

    const checkedPaths=new Set();
    let projects=[];
    let undoStack=[];
    let dragPayload=null;

    function cloneProjects(list){return JSON.parse(JSON.stringify(list||[]));}
    function pushUndo(){undoStack.push(cloneProjects(projects));if(undoStack.length>25)undoStack.shift();syncUndoBtn();}

    container.innerHTML=`
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
        <div>
          <h2 style="margin:0;font-size:18px">🧙‍♂️ Hard-Drive Folder Scan &amp; Gandalf Project Organizer</h2>
          <p class="muted small" style="margin:4px 0 0">1) Open any drive or folder below and check (<code>☑</code>) what to include · 2) Let <strong>Gandalf</strong> propose a project structure · 3) <strong>Drag cards together to merge</strong> or <strong>click / drag to split apart</strong>!</p>
        </div>
        <span class="w3-badge w3-badge-emerald" style="font-weight:700">✓ 20 Standing Foundry Skills Loaded</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:14px;margin-top:10px">
        <div style="padding:12px 14px;border-radius:10px;border:1px solid rgba(255,255,255,0.12);background:#0b101a;min-width:0">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
            <strong>1 · Hard Drives &amp; Proposed Folders</strong>
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              <button type="button" class="btn-mini btn" data-gw-scan-drives="1">🔍 Scan Hard Drives</button>
              <span class="muted small" data-gw-checked-count="1">0 checked</span>
            </div>
          </div>
          <div data-gw-tree-root="1" style="max-height:360px;overflow-y:auto;padding-right:4px;font-size:13px"></div>
          <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <button type="button" class="primary btn" data-gw-run-gandalf="1" style="font-weight:700">🧙‍♂️ Analyze Checked Folders with Gandalf →</button>
          </div>
        </div>
        <div style="padding:12px 14px;border-radius:10px;border:1px solid rgba(255,255,255,0.12);background:#0b101a;min-width:0;display:flex;flex-direction:column;gap:8px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
            <strong>2 · Gandalf Proposed Projects (Drag to Merge · Split Apart)</strong>
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              <button type="button" class="btn-mini btn" data-gw-undo="1" disabled>↩ Undo</button>
              <button type="button" class="btn-mini btn" data-gw-merge-selected="1" hidden>🔗 Merge Selected</button>
            </div>
          </div>
          <div data-gw-split-dropzone="1" style="padding:8px 10px;border-radius:8px;border:1px dashed rgba(56,189,248,0.5);background:rgba(14,27,44,0.6);color:#93c5fd;font-size:12px;text-align:center">
            💡 <strong>Drag one project card onto another</strong> to merge them · <strong>Drag any folder chip (📁) here</strong> or click <strong>✂️ Split Apart</strong> to split into its own project!
          </div>
          <div data-gw-projects-list="1" style="display:flex;flex-direction:column;gap:8px;max-height:380px;overflow-y:auto;padding-right:4px"></div>
          <div style="display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-top:auto;padding-top:6px">
            <span class="muted small" data-gw-status-msg="1">Check folders on the left and click Analyze with Gandalf.</span>
            <button type="button" class="primary btn emerald" data-gw-save-projects="1" disabled style="font-weight:700">✓ Create Proposed Projects</button>
          </div>
        </div>
      </div>
    `;

    const treeRoot=container.querySelector('[data-gw-tree-root]');
    const checkedCountEl=container.querySelector('[data-gw-checked-count]');
    const projectsListEl=container.querySelector('[data-gw-projects-list]');
    const splitDropzone=container.querySelector('[data-gw-split-dropzone]');
    const undoBtn=container.querySelector('[data-gw-undo]');
    const mergeSelBtn=container.querySelector('[data-gw-merge-selected]');
    const saveBtn=container.querySelector('[data-gw-save-projects]');
    const statusMsg=container.querySelector('[data-gw-status-msg]');
    const selectedProjectIds=new Set();

    function syncUndoBtn(){if(undoBtn)undoBtn.disabled=undoStack.length===0;}
    function updateCheckedLabel(){if(checkedCountEl)checkedCountEl.textContent=checkedPaths.size+' folder(s) checked';}

    function createTreeNode(item,depth,autoExpand){
      const wrap=document.createElement('div');
      wrap.style.marginLeft=(depth*14)+'px';
      const row=document.createElement('div');
      row.style.cssText='display:flex;align-items:center;gap:6px;padding:3px 4px;border-radius:5px';

      const expBtn=document.createElement('button');
      expBtn.type='button';
      expBtn.style.cssText='width:20px;height:20px;padding:0;border:0;background:transparent;color:#94a3b8;cursor:pointer;font-size:11px;flex:none';
      expBtn.textContent=item.has_children?(autoExpand?'▼':'▶'):'·';
      expBtn.disabled=!item.has_children;

      const chk=document.createElement('input');
      chk.type='checkbox';
      chk.dataset.treePath=item.path;
      chk.style.cssText='width:auto;margin:0;cursor:pointer';
      if(item.recommended && !checkedPaths.size){
        checkedPaths.add(item.path);
        if(Array.isArray(item.children)){
          item.children.forEach(ch=>{if(ch && ch.path)checkedPaths.add(ch.path);});
        }
      }
      chk.checked=checkedPaths.has(item.path);

      const lbl=document.createElement('span');
      lbl.style.cssText='cursor:pointer;word-break:break-all;font-size:12.5px';
      lbl.textContent='📁 '+(item.label||item.name);
      lbl.onclick=()=>{chk.checked=!chk.checked;chk.dispatchEvent(new Event('change'));};

      row.append(expBtn,chk,lbl);
      if(item.badge){
        const b=document.createElement('span');
        b.style.cssText='font-size:10.5px;padding:1px 6px;border-radius:999px;background:#1e293b;color:#93c5fd';
        b.textContent=item.badge;
        row.append(b);
      }

      const childBox=document.createElement('div');
      childBox.hidden=!autoExpand;
      let loadedChildren=Array.isArray(item.children)?item.children:null;

      function populateChildren(childrenArr){
        childBox.replaceChildren();
        if(!childrenArr || !childrenArr.length){
          const empty=document.createElement('div');
          empty.className='muted small';
          empty.style.marginLeft=((depth+1)*14+20)+'px';
          empty.textContent='(no subfolders)';
          childBox.append(empty);
          return;
        }
        childrenArr.forEach(ch=>{
          if(chk.checked && ch && ch.path)checkedPaths.add(ch.path);
          const cNode=createTreeNode(ch,depth+1,false);
          childBox.append(cNode);
        });
        updateCheckedLabel();
      }

      if(autoExpand && loadedChildren){
        populateChildren(loadedChildren);
      }

      expBtn.onclick=async()=>{
        if(!item.has_children)return;
        if(!childBox.hidden){
          childBox.hidden=true;
          expBtn.textContent='▶';
          return;
        }
        childBox.hidden=false;
        expBtn.textContent='▼';
        if(loadedChildren===null){
          childBox.textContent='Loading subfolders…';
          try{
            const res=await postWizardAction('scan_drive_tree',{parent_path:item.path});
            loadedChildren=(res && res.children)||[];
          }catch(_e){loadedChildren=[];}
        }
        populateChildren(loadedChildren);
      };

      chk.addEventListener('change',()=>{
        if(chk.checked)checkedPaths.add(item.path);
        else checkedPaths.delete(item.path);
        // Cascade toggle to any already-rendered child checkboxes if user checks/unchecks a parent folder
        childBox.querySelectorAll('input[type="checkbox"][data-tree-path]').forEach(subChk=>{
          subChk.checked=chk.checked;
          const sp=subChk.dataset.treePath;
          if(chk.checked)checkedPaths.add(sp);
          else checkedPaths.delete(sp);
        });
        updateCheckedLabel();
      });

      wrap.append(row,childBox);
      return wrap;
    }

    function renderDriveTree(treeData){
      treeRoot.replaceChildren();
      if(!treeData || ((!treeData.proposed_areas||!treeData.proposed_areas.length) && (!treeData.drives||!treeData.drives.length))){
        const hint=document.createElement('div');
        hint.className='muted small';
        hint.textContent='Click "🔍 Scan Hard Drives" above to load your drives and folders.';
        treeRoot.append(hint);
        return;
      }
      if(treeData.proposed_areas && treeData.proposed_areas.length){
        const h1=document.createElement('div');
        h1.style.cssText='font-size:11px;font-weight:700;color:#fbbf24;text-transform:uppercase;margin:2px 0 4px';
        h1.textContent='★ Proposed Work Areas (Expand to pick specific subfolders)';
        treeRoot.append(h1);
        treeData.proposed_areas.forEach(area=>{
          treeRoot.append(createTreeNode(area,0,Boolean(area.recommended)));
        });
      }
      if(treeData.drives && treeData.drives.length){
        const h2=document.createElement('div');
        h2.style.cssText='font-size:11px;font-weight:700;color:#93c5fd;text-transform:uppercase;margin:10px 0 4px';
        h2.textContent='💽 All Hard Drives';
        treeRoot.append(h2);
        treeData.drives.forEach(drv=>{
          treeRoot.append(createTreeNode(drv,0,false));
        });
      }
      updateCheckedLabel();
    }

    function mergeTwoProjects(targetIdx,sourceIdx){
      if(targetIdx===sourceIdx || !projects[targetIdx] || !projects[sourceIdx])return;
      pushUndo();
      const dst=projects[targetIdx];
      const src=projects[sourceIdx];
      const existingPaths=new Set((dst.folders||[]).map(f=>f.path));
      (src.folders||[]).forEach(f=>{if(!existingPaths.has(f.path))dst.folders.push(f);});
      if(!dst.name.includes('&') && dst.folders.length<=4){
        dst.name=dst.name.replace(/\s*\(\d+\s*Folders\)$/i,'')+' + '+src.name.replace(/\s*\(\d+\s*Folders\)$/i,'');
      }
      dst.gandalf_rationale='Merged project ('+dst.folders.length+' folders) — click Split Apart anytime.';
      projects.splice(sourceIdx,1);
      selectedProjectIds.clear();
      renderProjects();
    }

    function moveFolderChipToProject(srcProjIdx,folderIdx,dstProjIdx){
      if(srcProjIdx===dstProjIdx || !projects[srcProjIdx] || !projects[dstProjIdx])return;
      const folder=(projects[srcProjIdx].folders||[])[folderIdx];
      if(!folder)return;
      pushUndo();
      projects[srcProjIdx].folders.splice(folderIdx,1);
      projects[dstProjIdx].folders.push(folder);
      if(projects[srcProjIdx].folders.length===0){
        projects.splice(srcProjIdx,1);
      }
      renderProjects();
    }

    function splitSingleFolderOut(projIdx,folderIdx){
      const p=projects[projIdx];
      if(!p || !p.folders || p.folders.length<=1)return;
      const folder=p.folders[folderIdx];
      if(!folder)return;
      pushUndo();
      p.folders.splice(folderIdx,1);
      projects.splice(projIdx+1,0,{
        id:'proj-split-'+Date.now()+'-'+folderIdx,
        name:folder.name,
        group_folder:p.group_folder||'Software & AI Systems',
        seat:p.seat||'active',
        blurb:folder.blurb||('Standalone project for '+folder.name),
        gandalf_rationale:'Split into standalone project.',
        folders:[folder]
      });
      renderProjects();
    }

    function splitAllFoldersApart(projIdx){
      const p=projects[projIdx];
      if(!p || !p.folders || p.folders.length<=1)return;
      pushUndo();
      const newCards=p.folders.map((f,i)=>({
        id:'proj-split-'+Date.now()+'-'+i,
        name:f.name,
        group_folder:p.group_folder||'Software & AI Systems',
        seat:p.seat||'active',
        blurb:f.blurb||('Standalone project for '+f.name),
        gandalf_rationale:'Split apart from '+p.name+'.',
        folders:[f]
      }));
      projects.splice(projIdx,1,...newCards);
      renderProjects();
    }

    splitDropzone.addEventListener('dragover',ev=>{ev.preventDefault();splitDropzone.style.borderColor='#fbbf24';});
    splitDropzone.addEventListener('dragleave',()=>{splitDropzone.style.borderColor='rgba(56,189,248,0.5)';});
    splitDropzone.addEventListener('drop',ev=>{
      ev.preventDefault();
      splitDropzone.style.borderColor='rgba(56,189,248,0.5)';
      if(dragPayload && dragPayload.kind==='folder'){
        splitSingleFolderOut(dragPayload.projIdx,dragPayload.folderIdx);
      }
      dragPayload=null;
    });

    function renderProjects(){
      projectsListEl.replaceChildren();
      saveBtn.disabled=projects.length===0;
      mergeSelBtn.hidden=selectedProjectIds.size<2;
      if(mergeSelBtn)mergeSelBtn.textContent='🔗 Merge '+selectedProjectIds.size+' Selected';

      if(!projects.length){
        const empty=document.createElement('div');
        empty.className='muted small';
        empty.style.padding='12px 4px';
        empty.textContent='No project proposals yet — check one or more folders on the left and click "Analyze Checked Folders with Gandalf".';
        projectsListEl.append(empty);
        return;
      }

      projects.forEach((proj,pIdx)=>{
        const card=document.createElement('div');
        card.draggable=true;
        card.dataset.gandalfProjIdx=String(pIdx);
        card.style.cssText='padding:10px 12px;border-radius:9px;border:1px solid rgba(255,255,255,0.14);background:#121927;display:flex;flex-direction:column;gap:6px;cursor:grab';

        card.addEventListener('dragstart',ev=>{
          if(ev.target.closest('input,select,button,[data-folder-chip]'))return;
          dragPayload={kind:'project',projIdx:pIdx};
          if(ev.dataTransfer){ev.dataTransfer.effectAllowed='move';try{ev.dataTransfer.setData('text/plain','proj:'+pIdx);}catch(_e){}}
          card.style.opacity='0.6';
        });
        card.addEventListener('dragend',()=>{card.style.opacity='1';});
        card.addEventListener('dragover',ev=>{ev.preventDefault();card.style.borderColor='#4ade80';});
        card.addEventListener('dragleave',()=>{card.style.borderColor='rgba(255,255,255,0.14)';});
        card.addEventListener('drop',ev=>{
          ev.preventDefault();
          card.style.borderColor='rgba(255,255,255,0.14)';
          if(!dragPayload)return;
          if(dragPayload.kind==='project')mergeTwoProjects(pIdx,dragPayload.projIdx);
          else if(dragPayload.kind==='folder')moveFolderChipToProject(dragPayload.projIdx,dragPayload.folderIdx,pIdx);
          dragPayload=null;
        });

        const top=document.createElement('div');
        top.style.cssText='display:flex;align-items:center;gap:6px;flex-wrap:wrap';

        const selChk=document.createElement('input');
        selChk.type='checkbox';
        selChk.title='Select two or more cards to merge with 1 click';
        selChk.style.cssText='width:auto;margin:0;cursor:pointer';
        selChk.checked=selectedProjectIds.has(proj.id);
        selChk.onchange=()=>{
          if(selChk.checked)selectedProjectIds.add(proj.id);
          else selectedProjectIds.delete(proj.id);
          mergeSelBtn.hidden=selectedProjectIds.size<2;
          mergeSelBtn.textContent='🔗 Merge '+selectedProjectIds.size+' Selected';
        };

        const nameInp=document.createElement('input');
        nameInp.type='text';
        nameInp.value=proj.name;
        nameInp.style.cssText='flex:1;min-width:140px;padding:4px 8px;font-weight:700;font-size:13px;border-radius:6px;border:1px solid #334155;background:#0b101a;color:#f8fafc';
        nameInp.onchange=()=>{proj.name=nameInp.value.trim()||proj.name;};

        const seatSel=document.createElement('select');
        seatSel.style.cssText='width:auto;padding:4px 6px;font-size:12px;border-radius:6px;border:1px solid #334155;background:#0b101a;color:#e2e8f0';
        [['active','★ Active'],['deck','↳ On Deck'],['parked','○ Parked']].forEach(([v,lbl])=>{
          const opt=document.createElement('option');
          opt.value=v;opt.textContent=lbl;opt.selected=(proj.seat===v);
          seatSel.append(opt);
        });
        seatSel.onchange=()=>{proj.seat=seatSel.value;};

        top.append(selChk,nameInp,seatSel);

        if((proj.folders||[]).length>1){
          const splitBtn=document.createElement('button');
          splitBtn.type='button';
          splitBtn.className='btn-mini btn';
          splitBtn.style.cssText='padding:4px 8px;font-size:11.5px;cursor:pointer;border-color:#f59e0b;color:#fde68a';
          splitBtn.textContent='✂️ Split Apart ('+proj.folders.length+')';
          splitBtn.onclick=()=>splitAllFoldersApart(pIdx);
          top.append(splitBtn);
        }

        const rmBtn=document.createElement('button');
        rmBtn.type='button';
        rmBtn.className='btn-mini btn';
        rmBtn.title='Exclude from setup (never deletes files on disk)';
        rmBtn.style.cssText='padding:3px 7px;font-size:11px;opacity:0.75;cursor:pointer';
        rmBtn.textContent='✕';
        rmBtn.onclick=()=>{pushUndo();projects.splice(pIdx,1);renderProjects();};
        top.append(rmBtn);

        const rat=document.createElement('div');
        rat.className='muted small';
        rat.style.fontSize='11.5px';
        rat.textContent='🧙‍♂️ '+(proj.gandalf_rationale||proj.blurb||'');

        const chipsWrap=document.createElement('div');
        chipsWrap.style.cssText='display:flex;gap:6px;flex-wrap:wrap';
        (proj.folders||[]).forEach((f,fIdx)=>{
          const chip=document.createElement('span');
          chip.draggable=true;
          chip.dataset.folderChip='1';
          chip.title=f.path+' (drag to another project or drop above to split)';
          chip.style.cssText='display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:999px;background:#1e293b;border:1px solid #334155;font-size:11.5px;color:#e2e8f0;cursor:grab';
          chip.textContent='📁 '+f.name;
          chip.addEventListener('dragstart',ev=>{
            ev.stopPropagation();
            dragPayload={kind:'folder',projIdx:pIdx,folderIdx:fIdx};
            if(ev.dataTransfer){ev.dataTransfer.effectAllowed='move';try{ev.dataTransfer.setData('text/plain','folder:'+pIdx+':'+fIdx);}catch(_e){}}
          });
          if((proj.folders||[]).length>1){
            const pop=document.createElement('button');
            pop.type='button';
            pop.title='Split '+f.name+' into its own project';
            pop.style.cssText='border:0;background:transparent;color:#fbbf24;cursor:pointer;padding:0 2px;font-size:11px;font-weight:700';
            pop.textContent='✂';
            pop.onclick=ev=>{ev.stopPropagation();splitSingleFolderOut(pIdx,fIdx);};
            chip.append(pop);
          }
          chipsWrap.append(chip);
        });

        card.append(top,rat,chipsWrap);
        projectsListEl.append(card);
      });
    }

    container.querySelector('[data-gw-scan-drives]').onclick=async()=>{
      statusMsg.textContent='Scanning hard drives for folders…';
      try{
        const res=await postWizardAction('scan_drive_tree',{parent_path:''});
        renderDriveTree(res);
        statusMsg.textContent='✓ Hard drives scanned — check the folders or subfolders you want included.';
      }catch(e){statusMsg.textContent='Scan failed: '+e.message;}
    };

    container.querySelector('[data-gw-run-gandalf]').onclick=async()=>{
      const sel=Array.from(checkedPaths);
      if(!sel.length){
        statusMsg.textContent='⚠ Please check at least one folder or subfolder on the left first.';
        return;
      }
      statusMsg.textContent='🧙‍♂️ Gandalf is analyzing '+sel.length+' checked folder(s) & proposing project structure…';
      try{
        const res=await postWizardAction('gandalf_propose_projects',{selected_paths:sel});
        if(res && Array.isArray(res.proposed_projects)){
          pushUndo();
          projects=res.proposed_projects;
          renderProjects();
          statusMsg.textContent='✓ '+(res.message||('Proposed '+projects.length+' project(s).'));
        }else{
          statusMsg.textContent=(res && res.message)||'No folders found.';
        }
      }catch(e){statusMsg.textContent='Gandalf analysis error: '+e.message;}
    };

    undoBtn.onclick=()=>{
      if(!undoStack.length)return;
      projects=undoStack.pop();
      syncUndoBtn();
      renderProjects();
    };

    mergeSelBtn.onclick=()=>{
      const idxs=[];
      projects.forEach((p,i)=>{if(selectedProjectIds.has(p.id))idxs.push(i);});
      if(idxs.length<2)return;
      pushUndo();
      const first=projects[idxs[0]];
      const existing=new Set((first.folders||[]).map(f=>f.path));
      for(let k=idxs.length-1;k>=1;k--){
        const src=projects[idxs[k]];
        (src.folders||[]).forEach(f=>{if(!existing.has(f.path)){existing.add(f.path);first.folders.push(f);}});
        projects.splice(idxs[k],1);
      }
      first.gandalf_rationale='Merged '+first.folders.length+' folders together.';
      selectedProjectIds.clear();
      renderProjects();
    };

    saveBtn.onclick=async()=>{
      if(!projects.length)return;
      saveBtn.disabled=true;
      statusMsg.textContent='Creating '+projects.length+' project(s) & AI Cockpits…';
      try{
        const payload=projects.map(p=>({
          id:p.id,
          name:p.name,
          folder_path:p.folders[0].path,
          linked_material_paths:p.folders.map(f=>f.path),
          blurb:p.blurb||p.gandalf_rationale||'',
          group_folder:p.group_folder||'Software & AI Systems',
          seat:p.seat||'active',
          included:true,
          excluded:false
        }));
        const res=await postWizardAction('provision_projects_and_cockpits',{projects:payload});
        if(res && res.ok){
          statusMsg.textContent='🟢 Created '+(res.count||payload.length)+' Project(s) & AI Cockpits!';
          if($('wizBanner'))$('wizBanner').textContent='🟢 Created '+(res.count||payload.length)+' Project(s) & AI Cockpits!';
        }else{
          statusMsg.textContent='⚠ '+((res && (res.message||res.error))||'Could not create projects.');
        }
      }catch(e){statusMsg.textContent='Save failed: '+e.message;}
      finally{saveBtn.disabled=false;}
    };

    renderDriveTree(initialDriveTree);
    if(Array.isArray(initialProposals) && initialProposals.length){
      projects=cloneProjects(initialProposals);
    }
    renderProjects();
  }

  /* -----------------------------------------------------------------------
   * 4. Boot & Wire Listeners on Both /setup and /onboard-wizard (Zero POSTs on Load!)
   * --------------------------------------------------------------------- */
  function renderSkippedTailscaleLink(card){
    if(!card || !card.parentElement || $('setup-ts-undo-skip'))return;
    const note=document.createElement('div');
    note.id='setup-ts-undo-skip';
    note.className='muted small';
    note.style.cssText='margin:6px 0 10px;display:flex;align-items:center;gap:8px';
    const txt=document.createElement('span');
    txt.textContent='Tailscale skipped (running locally — automatic website updates work without Tailscale).';
    const undo=document.createElement('button');
    undo.type='button';
    undo.className='btn-mini';
    undo.textContent='Set up Tailscale';
    undo.onclick=()=>{
      try{localStorage.removeItem('anchor_skip_tailscale_prompt');}catch(_e){}
      note.remove();
      card.hidden=false;
    };
    note.append(txt,undo);
    card.parentElement.insertBefore(note,card);
  }

  if($('ms-reg-github-repo')){
    $('ms-reg-github-repo').value=CANONICAL_REPO;
    $('ms-reg-github-repo').readOnly=true;
  }
  if($('comms-imap-host')){
    $('comms-imap-host').addEventListener('input',()=>{userTouchedImapHost=true;});
  }

  function applyWizardBundle(b){
    if(!b)return;
    const prof=b.profile||{};
    const reg=b.registration||{};
    const lic=b.license_status||{};

    if(b.admin_edition===false){
      if($('btn-ms-push-update'))$('btn-ms-push-update').hidden=true;
      if(window._anchorSetupBridge && typeof window._anchorSetupBridge.clearCollabDemo==='function'){
        window._anchorSetupBridge.clearCollabDemo();
      }
      // Always open collaborator installs on Step 1 (Mother Ship & Remote) when no explicit ?section= was requested!
      const explicitSec=new URLSearchParams(location.search).get('section')||(location.hash?location.hash.replace('#',''):'');
      if(!explicitSec && (!reg.registered || !lic.accepted) && window._anchorSetupBridge){
        window._anchorSetupBridge.showSection('host');
      }
    }

    if($('ms-reg-email') && !$('ms-reg-email').value){
      $('ms-reg-email').value=reg.email||prof.contact_email||'';
    }
    if($('ms-reg-owner') && !$('ms-reg-owner').value && prof.configured){
      $('ms-reg-owner').value=prof.display_name||'';
    }
    if($('ms-reg-pseudonym') && !$('ms-reg-pseudonym').value && prof.pseudonym){
      $('ms-reg-pseudonym').value=prof.pseudonym;
    }
    if(reg.registered && $('ms-reg-status-badge')){
      $('ms-reg-status-badge').textContent='🟢 Registered ('+(reg.email||'Saved Locally')+')';
      $('ms-reg-status-badge').className='w3-badge w3-badge-emerald';
    }

    const ts=b.tailscale||{};
    let tsDismissed=false;
    try{tsDismissed=localStorage.getItem('anchor_skip_tailscale_prompt')==='1';}catch(_e){}
    const tsCard=$('setup-tailscale-prompt-card');
    if(tsCard && (!ts.installed || !ts.running)){
      if(!tsDismissed){
        tsCard.hidden=false;
        if($('setup-ts-prompt-badge')){
          $('setup-ts-prompt-badge').textContent=ts.installed?'Installed · Not Signed In':'Not Installed';
        }
      }else{
        renderSkippedTailscaleLink(tsCard);
      }
    }

    if(b.browser_accounts && b.browser_accounts.accounts){
      renderAllProviderStrips(b.browser_accounts.accounts);
    }
    if(b.email_status){
      updateEmailBadge(b.email_status);
    }
    if(b.variable_strength && $('wizVariableStrengthCard')){
      mountWizardVariableStrength($('wizVariableStrengthCard'), b.variable_strength);
    }

    const savedProposals=(b.state && b.state.projects && b.state.projects.gandalf_proposals)||[];
    document.querySelectorAll('[data-gandalf-workbench="1"]').forEach(el=>{
      mountGandalfDriveWorkbench(el,b.drive_tree||null,savedProposals);
    });
  }

  if(window.ONBOARD_WIZARD_BOOT){
    applyWizardBundle(window.ONBOARD_WIZARD_BOOT);
  }else{
    getWizardState().then(applyWizardBundle).catch(()=>{});
  }

  if($('btn-setup-ts-yes'))$('btn-setup-ts-yes').onclick=async()=>{
    const msg=$('setup-ts-prompt-msg');
    if(msg)msg.textContent='Installing / launching Tailscale sign-in…';
    try{
      const res=await postWizardAction('setup_tailscale_interactive',{});
      if(msg)msg.textContent=res.message||'Tailscale setup launched — complete sign-in in your browser.';
    }catch(e){if(msg)msg.textContent='Tailscale launch note: '+e.message;}
  };
  if($('btn-setup-ts-skip'))$('btn-setup-ts-skip').onclick=()=>{
    try{localStorage.setItem('anchor_skip_tailscale_prompt','1');}catch(_e){}
    const tsCard=$('setup-tailscale-prompt-card');
    if(tsCard){
      tsCard.hidden=true;
      renderSkippedTailscaleLink(tsCard);
    }
  };
  if($('btn-setup-auto-install-clis'))$('btn-setup-auto-install-clis').onclick=async()=>{
    const msg=$('setup-cli-browser-msg'),btn=$('btn-setup-auto-install-clis');
    if(btn)btn.disabled=true;
    if(msg)msg.textContent='Installing all 4 Agent CLIs (Claude Code, Gemini / Antigravity, OpenAI Codex, and Grok)…';
    try{
      const res=await postWizardAction('auto_install_clis',{include_grok:true});
      if(msg)msg.textContent=res.message||'✓ All 4 Agent CLIs installed & verified.';
      if(res && res.accounts)renderAllProviderStrips(res.accounts);
    }catch(e){if(msg)msg.textContent='CLI install error: '+e.message;}
    finally{if(btn)btn.disabled=false;}
  };
  if($('btn-setup-check-browser-accounts'))$('btn-setup-check-browser-accounts').onclick=async()=>{
    const msg=$('setup-cli-browser-msg');
    if(msg)msg.textContent='Refreshing CLI connection status…';
    try{
      const res=await postWizardAction('detect_browser_accounts',{include_browser_history:false});
      if(res && res.accounts)renderAllProviderStrips(res.accounts);
      if(msg)msg.textContent='✓ Connection status updated.';
    }catch(e){if(msg)msg.textContent='Refresh error: '+e.message;}
  };

  if($('comms-email'))$('comms-email').addEventListener('input',ev=>detectEmailDomainAndFill(ev.target.value));
  if($('simple-comms-email'))$('simple-comms-email').addEventListener('input',ev=>detectEmailDomainAndFill(ev.target.value));

  if($('btn-comms-quick-outlook'))$('btn-comms-quick-outlook').onclick=async()=>{
    const msg=$('simple-comms-msg');
    if(msg)msg.textContent='Connecting running Windows Outlook…';
    try{
      const res=await postWizardAction('connect_email_simple',{use_outlook:true});
      if(msg)msg.textContent=res.message||'Checked Windows Outlook.';
      if(res && res.connected){
        updateEmailBadge({connected:true,status_label:res.status_label||'Connected',primary_email:res.email||'Windows Outlook'});
      }
    }catch(e){if(msg)msg.textContent='Outlook check note: '+e.message;}
  };

  if($('btn-comms-open-provider-app-pwd'))$('btn-comms-open-provider-app-pwd').onclick=()=>{
    const em=($('simple-comms-email')&&$('simple-comms-email').value)||($('comms-email')&&$('comms-email').value)||'';
    const hit=detectEmailDomainAndFill(em);
    const url=(hit && hit.app_pwd_url)||'https://myaccount.google.com/apppasswords';
    window.open(url,'_blank','noopener,noreferrer');
    if($('simple-comms-secret'))$('simple-comms-secret').focus();
    else if($('comms-secret'))$('comms-secret').focus();
  };

  if($('btn-simple-comms-connect'))$('btn-simple-comms-connect').onclick=async()=>{
    const em=($('simple-comms-email')&&$('simple-comms-email').value)||($('comms-email')&&$('comms-email').value)||'';
    const sec=($('simple-comms-secret')&&$('simple-comms-secret').value)||($('comms-secret')&&$('comms-secret').value)||'';
    const msg=$('simple-comms-msg');
    const btn=$('btn-simple-comms-connect');
    if(btn)btn.disabled=true;
    if(msg)msg.textContent='Verifying email connection…';
    try{
      const res=await postWizardAction('connect_email_simple',{email:em,secret:sec});
      if(res && res.connected){
        updateEmailBadge({connected:true,status_label:res.status_label||('Connected ('+em+')'),primary_email:res.email||em});
        if($('simple-comms-secret'))$('simple-comms-secret').value='';
        if(msg)msg.textContent='🟢 '+(res.message||'Connected!');
      }else{
        if(res && res.needs_password && res.app_password_url){
          window.open(res.app_password_url,'_blank','noopener,noreferrer');
        }
        if(msg)msg.textContent='⚠ '+((res && res.message)||'Could not connect — check password.');
      }
    }catch(e){if(msg)msg.textContent='Connection failed: '+e.message;}
    finally{if(btn)btn.disabled=false;}
  };
})();
