(function(){
  'use strict';
  const api=window.AnchorProviders,$=id=>document.getElementById(id);
  const CANONICAL_REPO='https://github.com/johncliechty/ghostworldlabs-anchor';
  const EMAIL_PROVIDERS={
    'gmail.com':{family:'gmail',label:'Primary Gmail & Calendar',imap_host:'imap.gmail.com',imap_port:993,app_pwd_url:'https://myaccount.google.com/apppasswords',provider_name:'Google / Gmail',verified:true},
    'googlemail.com':{family:'gmail',label:'Primary Gmail & Calendar',imap_host:'imap.gmail.com',imap_port:993,app_pwd_url:'https://myaccount.google.com/apppasswords',provider_name:'Google / Gmail',verified:true},
    'outlook.com':{family:'outlook',label:'Microsoft Outlook & Calendar',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Recommended: use 1-Click Local Windows Outlook or Microsoft 365 OAuth.'},
    'hotmail.com':{family:'outlook',label:'Microsoft Hotmail / Outlook',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Recommended: use 1-Click Local Windows Outlook or Microsoft 365 OAuth.'},
    'live.com':{family:'outlook',label:'Microsoft Live / Outlook',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Recommended: use 1-Click Local Windows Outlook or Microsoft 365 OAuth.'},
    'msn.com':{family:'outlook',label:'Microsoft MSN / Outlook',imap_host:'outlook.office365.com',imap_port:993,app_pwd_url:'https://account.live.com/proofs/AppPassword',provider_name:'Microsoft Outlook',verified:true,auth_hint:'Recommended: use 1-Click Local Windows Outlook or Microsoft 365 OAuth.'},
    'yahoo.com':{family:'custom',label:'Yahoo Mail & Calendar',imap_host:'imap.mail.yahoo.com',imap_port:993,app_pwd_url:'https://login.yahoo.com/account/security',provider_name:'Yahoo Mail',verified:true},
    'ymail.com':{family:'custom',label:'Yahoo Mail & Calendar',imap_host:'imap.mail.yahoo.com',imap_port:993,app_pwd_url:'https://login.yahoo.com/account/security',provider_name:'Yahoo Mail',verified:true},
    'icloud.com':{family:'custom',label:'Apple iCloud Mail & Calendar',imap_host:'imap.mail.me.com',imap_port:993,app_pwd_url:'https://appleid.apple.com/account/manage',provider_name:'Apple iCloud',verified:true},
    'me.com':{family:'custom',label:'Apple iCloud Mail & Calendar',imap_host:'imap.mail.me.com',imap_port:993,app_pwd_url:'https://appleid.apple.com/account/manage',provider_name:'Apple iCloud',verified:true}
  };
  let loginPollTimer=null;
  let userTouchedImapHost=false;

  function renderBrowserAccountsStrip(accountsMap){
    const strip=$('setup-browser-accounts-strip');
    if(!strip || !accountsMap)return;
    strip.replaceChildren();
    const order=['claude','gemini','chatgpt','grok'];
    order.forEach(fam=>{
      const info=accountsMap[fam];
      if(!info)return;
      const box=document.createElement('div');
      box.style.cssText='padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);background:#0c111b;display:flex;flex-direction:column;gap:6px';
      const top=document.createElement('div');
      top.style.cssText='display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap';
      const title=document.createElement('strong');
      title.textContent=info.label||fam;
      const badge=document.createElement('span');
      badge.className='w3-badge '+(info.cli_authenticated?'w3-badge-emerald':(info.browser_session_detected?'w3-badge-sky':'w3-badge-amber'));
      badge.textContent=info.cli_authenticated?'✓ Signed In':(info.browser_session_detected?'🌐 Browser Account Found':'Sign In Ready');
      top.append(title,badge);
      const sub=document.createElement('div');
      sub.className='muted small';
      sub.textContent=(info.cli_installed?'CLI installed':'CLI not installed yet')+' · '+(info.status_summary||'');
      const btn=document.createElement('button');
      btn.type='button';
      btn.className='btn-mini primary';
      btn.textContent=info.cli_authenticated?'↻ Re-Verify / Switch Account':'🌐 Open Browser & Log In';
      btn.onclick=()=>triggerBrowserLogin(fam);
      box.append(top,sub,btn);
      strip.append(box);
    });
  }

  async function refreshBrowserAccounts(includeBrowserHistory){
    if(!api || !api.request)return null;
    try{
      const res=await api.request('/api/onboard-wizard/action',{
        action:'detect_browser_accounts',
        include_browser_history:Boolean(includeBrowserHistory)
      });
      if(res && res.accounts)renderBrowserAccountsStrip(res.accounts);
      return res;
    }catch(_e){return null;}
  }

  async function triggerBrowserLogin(fam){
    const msg=$('setup-cli-browser-msg');
    if(msg)msg.textContent='Opening browser & CLI login for '+fam+'…';
    try{
      const res=await api.request('/api/onboard-wizard/action',{action:'open_browser_login',family:fam});
      if(res && typeof res.login_url==='string' && res.login_url.startsWith('https://') && !res.opened_on_host){
        window.open(res.login_url,'_blank','noopener,noreferrer');
      }
      if(msg)msg.textContent=res.message||('Browser opened for '+fam+' — sign in there and Anchor will detect it automatically.');
      clearInterval(loginPollTimer);
      let ticks=0;
      loginPollTimer=setInterval(async()=>{
        ticks+=1;
        const cur=await refreshBrowserAccounts(false);
        const fInfo=cur && cur.accounts && cur.accounts[fam];
        if(fInfo && fInfo.cli_authenticated){
          clearInterval(loginPollTimer);
          if(msg)msg.textContent='✓ '+fInfo.label+' is now signed in and ready!';
          if($('provider-refresh'))$('provider-refresh').click();
          return;
        }
        if(ticks>=60){
          clearInterval(loginPollTimer);
          if(msg)msg.textContent='Still waiting for sign-in — click Scan Open Browser Accounts once you finish signing in.';
        }
      },3000);
    }catch(e){
      if(msg)msg.textContent='Could not launch browser login: '+e.message;
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
      auth_hint:'Suggested host — verify with your mail provider or use 1-Click Local Outlook.'
    };
    if($('comms-family'))$('comms-family').value=hit.family;
    if($('comms-label') && !$('comms-label').value)$('comms-label').value=hit.label;
    if($('comms-imap-host') && (!userTouchedImapHost || !$('comms-imap-host').value))$('comms-imap-host').value=hit.imap_host;
    if($('comms-imap-port') && !userTouchedImapHost)$('comms-imap-port').value=String(hit.imap_port);
    if($('btn-comms-open-provider-app-pwd')){
      $('btn-comms-open-provider-app-pwd').disabled=!hit.app_pwd_url;
    }
    if($('comms-detected-provider-hint')){
      const prefix=hit.verified?'✓ Auto-detected ':'ℹ Suggested ';
      $('comms-detected-provider-hint').textContent=prefix+hit.provider_name+' ('+hit.imap_host+':'+hit.imap_port+').'+(hit.auth_hint?(' '+hit.auth_hint):'');
    }
    return hit;
  }

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

  fetch('/api/onboard-wizard/state',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(b=>{
    if(!b)return;
    if(b.admin_edition===false){
      if($('btn-ms-push-update'))$('btn-ms-push-update').hidden=true;
    }
    const prof=b.profile||{};
    const reg=b.registration||{};
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
      $('ms-reg-status-badge').textContent='✓ Registered ('+(reg.email||'Saved Locally')+')';
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
      renderBrowserAccountsStrip(b.browser_accounts.accounts);
    }else{
      refreshBrowserAccounts(false);
    }
  }).catch(()=>{});

  if($('btn-setup-ts-yes'))$('btn-setup-ts-yes').onclick=async()=>{
    const msg=$('setup-ts-prompt-msg');
    if(msg)msg.textContent='Installing / launching Tailscale sign-in…';
    try{
      const res=await api.request('/api/onboard-wizard/action',{action:'setup_tailscale_interactive'});
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
    const incGrok=Boolean($('chk-setup-install-grok') && $('chk-setup-install-grok').checked);
    if(btn)btn.disabled=true;
    if(msg)msg.textContent='Installing Claude Code CLI, Antigravity/Gemini CLI & OpenAI Codex CLI'+(incGrok?' + Grok CLI':'')+'…';
    try{
      const res=await api.request('/api/onboard-wizard/action',{action:'auto_install_clis',include_grok:incGrok});
      if(msg)msg.textContent=res.message||'✓ CLI check & auto-install complete.';
      await refreshBrowserAccounts(false);
    }catch(e){if(msg)msg.textContent='CLI install error: '+e.message;}
    finally{if(btn)btn.disabled=false;}
  };
  if($('btn-setup-check-browser-accounts'))$('btn-setup-check-browser-accounts').onclick=async()=>{
    const msg=$('setup-cli-browser-msg');
    if(msg)msg.textContent='Checking open browser provider domains (read-only) & local CLI credentials…';
    await refreshBrowserAccounts(true);
    if(msg)msg.textContent='✓ Updated browser & CLI account status (read-only domain check).';
  };
  if($('comms-email'))$('comms-email').addEventListener('change',ev=>detectEmailDomainAndFill(ev.target.value));
  if($('btn-comms-quick-outlook'))$('btn-comms-quick-outlook').onclick=()=>{
    if($('btn-comms-auto-outlook'))$('btn-comms-auto-outlook').click();
  };
  if($('btn-comms-open-provider-app-pwd'))$('btn-comms-open-provider-app-pwd').onclick=()=>{
    const em=$('comms-email')?$('comms-email').value:'';
    const hit=detectEmailDomainAndFill(em);
    const url=hit && hit.app_pwd_url;
    if(!url || !url.startsWith('https://')){
      if($('comms-detected-provider-hint')){
        $('comms-detected-provider-hint').textContent='Check your email provider security settings for an IMAP App Password, or click 1-Click Local Outlook.';
      }
      return;
    }
    window.open(url,'_blank','noopener,noreferrer');
    if($('comms-secret'))$('comms-secret').focus();
  };
})();
