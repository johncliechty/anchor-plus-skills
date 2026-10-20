(function(){
  'use strict';
  const api=window.AnchorProviders,$=id=>document.getElementById(id);
  if(window.parent!==window || new URLSearchParams(location.search).get('embed')==='1'){
    document.body.classList.add('is-embedded');
  }
  let loginWindow,openedLogin;
  let data,family='claude',connectionId,controller,login,poll;

  // ── Wave 3 State & Persistence ──────────────────────────────────────────
  let w3Synced=false;
  let w3RoleFilter='all';
  let w3SearchFilter='';
  let w3ActivePreset='recent';
  let w3LastExcludedUndo=null;
  let w3DraggedFolderId=null;

  const W3_DEFAULT_STATE={
    primary_root:'C:\\dev',
    external_roots:[
      {id:'ext-obsidian',path:'D:\\ObsidianVault\\ResearchNotes',label:'External · Linked',mode:'read_write'}
    ],
    project_groups:[
      {id:'grp-core',name:'Anchor Core & Control Plane',icon:'⚓',desc:'Primary control plane, Cave of Wonders UI, Tailscale/GitHub bridge, and Steward orchestration'},
      {id:'grp-foundry',name:'Skill Foundry & Trio Engines',icon:'⚒',desc:'researchPrime, Crucible, Foreman, Gandalf, and automated evaluation suites'},
      {id:'grp-quant',name:'Quant, Valuation & Bio-Compute',icon:'📈',desc:'Exact-Decimal financial modeling, algorithmic trading pipelines, and neuroscience simulations'},
      {id:'grp-archive',name:'Personal Archive & Unsorted',icon:'🗂',desc:'Legacy repositories, reference documentation, and standalone utilities'}
    ],
    folders:[
      {
        id:'f-anchor',name:'Anchor',path:'C:\\dev\\Anchor',source:'primary',gitBranch:'main',gitClean:true,
        filesCount:318,lastMod:'2m ago',role:'active',parentId:null,groupId:'grp-core',
        liveWork:true,liveWorkDetail:'1 active Steward session · AnchorServerDaemon :8777',
        desc:'Mother Ship HTTP server, High Seat, Cave of Wonders & Provider Setup',
        cockpits:[
          {id:'cp-anchor-1',name:'Steward Ecgberht (High Seat)',engine:'claude-fable-5-1 · max',status:'Running'},
          {id:'cp-anchor-2',name:'Setup & Provider Verification',engine:'gemini-4-argon · high',status:'Ready'}
        ]
      },
      {
        id:'f-foundry',name:'Skill Foundry',path:'C:\\dev\\Skill Foundry',source:'primary',gitBranch:'main',gitClean:true,
        filesCount:204,lastMod:'38m ago',role:'active',parentId:null,groupId:'grp-foundry',
        liveWork:false,liveWorkDetail:'',
        desc:'Portfolio of 18+ specialized agent skills (Gandalf, Ramanujan, Legal Beagle, Figure Designer)',
        cockpits:[
          {id:'cp-sf-1',name:'Foundry Sleep-Cycle Auditor',engine:'claude-fable-5-1 · max',status:'Ready'}
        ]
      },
      {
        id:'f-trio',name:'trio',path:'C:\\dev\\trio',source:'primary',gitBranch:'main',gitClean:true,
        filesCount:142,lastMod:'1h ago',role:'subordinate',parentId:'f-foundry',groupId:'grp-foundry',
        liveWork:false,liveWorkDetail:'',
        desc:'Core researchPrime → Crucible → Foreman Node orchestration engines',
        cockpits:[]
      },
      {
        id:'f-autoharness',name:'AutoHarness',path:'C:\\dev\\AutoHarness',source:'primary',gitBranch:'feat/eval-loop',gitClean:true,
        filesCount:89,lastMod:'4h ago',role:'subordinate',parentId:'f-foundry',groupId:'grp-foundry',
        liveWork:false,liveWorkDetail:'',
        desc:'Automated benchmark & regression harness for multi-agent skill verification',
        cockpits:[]
      },
      {
        id:'f-fin',name:'financial-models',path:'C:\\dev\\financial-models',source:'primary',gitBranch:'main',gitClean:true,
        filesCount:64,lastMod:'1d ago',role:'active',parentId:null,groupId:'grp-quant',
        liveWork:false,liveWorkDetail:'',
        desc:'Exact-Decimal VC round comp & real-estate equity waterfall models',
        cockpits:[
          {id:'cp-fin-1',name:'Deal Flow & Waterfall Analyst',engine:'gpt-6.1-sol · ultra',status:'Ready'}
        ]
      },
      {
        id:'f-trading',name:'quant-backtest',path:'C:\\dev\\quant-backtest',source:'primary',gitBranch:'main',gitClean:true,
        filesCount:112,lastMod:'2d ago',role:'subordinate',parentId:'f-fin',groupId:'grp-quant',
        liveWork:false,liveWorkDetail:'',
        desc:'Historical tick simulation and cross-asset regime filter scripts',
        cockpits:[]
      },
      {
        id:'f-obsidian',name:'ResearchNotes (Obsidian)',path:'D:\\ObsidianVault\\ResearchNotes',source:'external',gitBranch:'vault-sync',gitClean:true,
        filesCount:490,lastMod:'15m ago',role:'active',parentId:null,groupId:'grp-quant',
        liveWork:false,liveWorkDetail:'',
        desc:'External knowledge base & literature notes linked without copying vault binaries',
        cockpits:[
          {id:'cp-obs-1',name:'Literature Synthesis & PRISMA',engine:'gemini-4-argon · high',status:'Ready'}
        ]
      },
      {
        id:'f-legacy',name:'old-scratch-2024',path:'C:\\dev\\old-scratch-2024',source:'primary',gitBranch:'detached',gitClean:false,
        filesCount:27,lastMod:'4mo ago',role:'excluded',parentId:null,groupId:'grp-archive',
        liveWork:false,liveWorkDetail:'',
        desc:'Deprecated prototype scripts — excluded from Star Chart indexing',
        cockpits:[]
      }
    ],
    goal_tiles:[
      {
        id:'goal-1',act:'ACT I · FOUNDATION & COCKPIT',horizon:'Q3 2026',
        title:'Ship Unified Cave of Wonders Setup & 3-Stage Onboarding',
        desc:'Unify Mother Ship host checks, 4-provider native subscription matrix, and interactive Star Chart workspace onboarding into a single cohesive setup surface.',
        linkedGroup:'grp-core',status:'In Progress · 85%',color:'amber',
        milestones:[
          {text:'Wave 1: Mother Ship, Tailscale & GitHub Setup card',done:true},
          {text:'Wave 2: 4-Provider Subscription Matrix & Tier Routing',done:true},
          {text:'Wave 3: Star Chart & Workspace Onboarding live wiring',done:false}
        ]
      },
      {
        id:'goal-2',act:'ACT II · AUTONOMOUS SWARM RELIABILITY',horizon:'Q3–Q4 2026',
        title:'Zero-Orphan Multi-Wave Foreman & Crucible Execution',
        desc:'Harden Trio + Skill Foundry orchestration with cross-family Shark Tank verification, automatic rate-limit failover, and Zombie Hunter process protection.',
        linkedGroup:'grp-foundry',status:'Active · 60%',color:'teal',
        milestones:[
          {text:'Enforce cross-family verification stamps across all skills',done:true},
          {text:'Wire 10-minute status cadence & automated usage journaling',done:true},
          {text:'Complete AutoHarness nightly regression benchmarks',done:false}
        ]
      },
      {
        id:'goal-3',act:'ACT III · QUANT & RESEARCH PIPELINE',horizon:'Q4 2026',
        title:'Unify Financial-Analyst Waterfalls & Live Backtest Cockpits',
        desc:'Connect exact-Decimal Python/Excel valuation models with live market data feeds and Obsidian literature synthesis under dedicated AI cockpits.',
        linkedGroup:'grp-quant',status:'Planned · 25%',color:'purple',
        milestones:[
          {text:'Link D:\\ObsidianVault\\ResearchNotes as external knowledge root',done:true},
          {text:'Spawn Quant Researcher + Backtest Runner cockpit pair',done:false}
        ]
      }
    ],
    pull_history:[
      {id:'pull-8901',ts:'Today 14:22',src:'C:\\Users\\example\\Documents\\Neuro-Circuit-Notes',dest:'C:\\dev\\example\\Neuro-Circuit-Notes',files:19,size:'3.1 MB',sha256:'a94f...8c12',undone:false}
    ],
    search_presets:{
      recent:[
        {id:'sp-1',name:'Options-Flow-Scanner',src:'C:\\Users\\example\\Downloads\\Options-Flow-Scanner',destSubpath:'imported\\Options-Flow-Scanner',files:34,size:'4.2 MB',age:'Modified 3h ago',matchReason:'Python package + git repo in Downloads',suggestedGroup:'grp-quant'},
        {id:'sp-2',name:'BioCompute-SpikeSim',src:'C:\\Users\\example\\Desktop\\BioCompute-SpikeSim',destSubpath:'imported\\BioCompute-SpikeSim',files:51,size:'8.7 MB',age:'Modified yesterday',matchReason:'Active Jupyter + PyTorch project on Desktop',suggestedGroup:'grp-quant'}
      ],
      code:[
        {id:'sp-3',name:'mcp-bridge-prototype',src:'C:\\Users\\example\\Documents\\repos\\mcp-bridge-prototype',destSubpath:'imported\\mcp-bridge-prototype',files:22,size:'1.1 MB',age:'Modified 5d ago',matchReason:'Contains pyproject.toml + .git outside C:\\dev',suggestedGroup:'grp-core'}
      ],
      docs:[
        {id:'sp-4',name:'Series-B-TermSheets-2026',src:'C:\\Users\\example\\Documents\\Deals\\Series-B-TermSheets-2026',destSubpath:'imported\\Series-B-TermSheets-2026',files:14,size:'6.8 MB',age:'Modified 2d ago',matchReason:'Markdown + XLSX financial model bundle',suggestedGroup:'grp-quant'}
      ]
    }
  };
  let w3State=JSON.parse(JSON.stringify(W3_DEFAULT_STATE));

  function text(tag,value,className){const node=document.createElement(tag);node.textContent=value;if(className)node.className=className;return node;}
  function button(title,action){const b=text('button',title);b.type='button';b.onclick=()=>Promise.resolve(action()).catch(error=>{$('setup-message').textContent=error.message;$('setup-message').className='error';});return b;}
  function section(name){
    ['host','providers','chart','comms'].forEach(s=>{const el=$('setup-section-'+s);if(el)el.hidden=s!==name;});
    document.querySelectorAll('.setup-steps [data-section]').forEach(b=>{if(b.dataset.section===name)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
    document.querySelectorAll('.cave-rail-stage').forEach(b=>b.classList.toggle('is-active',b.getAttribute('data-rail-section')===name));
    if(name==='chart' && !w3Synced){syncWave3FromServer();}
    if(name==='comms'){syncWave9CommsFromServer();}
  }
  function leave(){if(window.parent!==window)window.parent.postMessage({type:'anchor-setup-close'},location.origin);else location.href=(window.pywebview?'/static/app.html':'/high-seat');}
  function active(){return data.connections.find(c=>c.id===connectionId) || data.connections.find(c=>c.family===family);}
  function reportFacts(parent,account){
    const monAll=(data && data.usage_summary && data.usage_summary.allowance_monitor && data.usage_summary.allowance_monitor.families) || {};
    const mon=(account && account.native_default && account.mode==='subscription') ? (monAll[account.family] || null) : null;
    const capText = (account && account.allowance && account.allowance.windows && account.allowance.windows.length)
      ? api.capacityText(account)
      : (mon && mon.summary_line) ? (mon.summary_line + ' (' + api.capacityText(account) + ')') : api.capacityText(account);
    const facts=document.createElement('dl');facts.className='provider-facts';
    const rows=[['Account identity',account.account_identity || 'Not reported by native status'],['Connection source',account.connection_source || account.auth_source],['Native sign-in',account.auth.replaceAll('_',' ')+(account.auth_stale?' · stale':'')],['Connection test',account.test+' · status/account command only'],
      ['Verified frontier model',(mon && mon.frontier_model) || 'Not reported'],
      ['Subscription allowance',capText],['Allowance source / observed',(mon && mon.basis_label ? mon.basis_label+' · ' : '')+account.allowance.source+' · '+(account.allowance.observed_at || 'Not reported')],
      ['Exact tokens remaining','Not reported'],['Provider account token activity',account.provider_usage.tokens===null ? 'Not reported · '+account.provider_usage.state : account.provider_usage.tokens.toLocaleString()+' lifetime tokens · '+account.provider_usage.state],
      ['Token activity source / observed',account.provider_usage.source+' · '+(account.provider_usage.observed_at || 'Not reported')],
      ['Anchor-observed consumption',account.anchor_observed.tokens===null ? 'Not reported; legacy observations have no account attribution' : account.anchor_observed.tokens.toLocaleString()+' tokens · '+account.anchor_observed.period+(account.anchor_observed.state==='stale'?' · stale':'')],
      ['Anchor source / observed',account.anchor_observed.source+' · '+(account.anchor_observed.observed_at || 'Not reported')],
      ['API spend','Not reported · '+account.api_spend.state],['Subscription price','Not reported · '+account.subscription_price.state]];
    rows.forEach(([label,value])=>{const cell=document.createElement('div');cell.append(text('dt',label),text('dd',value));facts.append(cell);});parent.append(facts);
    account.allowance.windows.forEach(w=>{parent.append(text('p',w.label+' · '+w.remaining_percent+'% remaining'+(account.allowance.state==='stale'?' · stale':'')));const meter=document.createElement('div');meter.className='provider-meter';const fill=document.createElement('span');fill.style.width=w.remaining_percent+'%';meter.append(fill);parent.append(meter);});
    if(account.warning)parent.append(text('p',account.warning,'setup-notice near_limit'));
    if(account.allowance.state==='stale')parent.append(text('p','Stale report retained. Refresh on the host before treating it as current capacity.','setup-notice stale'));
  }
  function drawWave2Matrix(){
    const matrix=$('wave2-provider-matrix');
    if(!matrix || !data)return;
    matrix.replaceChildren();
    const us=data.usage_summary && data.usage_summary.windows;
    const w7=us && us['7d'], w30=us && us['30d'];
    const monFamilies=(data.usage_summary && data.usage_summary.allowance_monitor && data.usage_summary.allowance_monitor.families) || {};
    if($('wave2-spend-summary-line') && w7 && w30){
      $('wave2-spend-summary-line').textContent='Portfolio API Equivalent Value: 7d ~'+api.fmtUsd(w7.hypothetical_usd)+' ('+api.fmtTokens(w7.total_tokens)+' tok) · 30d ~'+api.fmtUsd(w30.hypothetical_usd)+' ('+api.fmtTokens(w30.total_tokens)+' tok).';
    }
    const defaultFrontiers={claude:'claude-fable-5-1 · max',chatgpt:'gpt-6.1-sol · ultra',gemini:'gemini-4-argon · high',grok:'grok-4.7 · xhigh'};
    Object.entries(api.labels).forEach(([key,label])=>{
      const list=data.connections.filter(c=>c.family===key);
      const selectedId=(data.preferences && data.preferences.accounts && data.preferences.accounts[key]) || '';
      const primary=list.find(c=>c.id===selectedId) || list[0];
      const mon=monFamilies[key] || {};
      const isSignedOrReady=Boolean((primary && primary.auth==='signed_in') || mon.connected);
      const authBadgeText=(primary && primary.auth && primary.auth!=='unknown') ? primary.auth.replaceAll('_',' ') : (mon.connected ? 'CLI ready' : (primary ? primary.auth.replaceAll('_',' ') : 'none'));
      const card=document.createElement('div');
      card.className='wave2-matrix-card'+(key===family?' is-selected':'');
      const top=document.createElement('div');
      top.className='wave2-matrix-top';
      top.append(text('strong',label),text('span',authBadgeText,'w3-badge '+(isSignedOrReady?'w3-badge-emerald':'w3-badge-amber')));
      const sel=primary && primary.catalog && primary.catalog.selection;
      const selModel=sel && sel.model;
      const selEffort=sel && sel.effort;
      const frontierLabel=selModel ? (selModel==='best'?'claude-fable-5-1 · max (best)':(selEffort ? selModel+' · '+selEffort : selModel)) : (mon.frontier_model || defaultFrontiers[key] || 'Frontier');
      const meta=document.createElement('div');
      meta.className='wave2-matrix-meta';
      meta.append(text('span','⚡ Frontier: '+frontierLabel));
      const allowanceText=(primary && primary.allowance && primary.allowance.windows && primary.allowance.windows.length)
        ? api.capacityText(primary)
        : (mon.summary_line || (primary ? api.capacityText(primary) : 'Not reported'));
      meta.append(text('span',allowanceText));
      const fam7=w7 && w7.by_family && w7.by_family[key];
      const fam30=w30 && w30.by_family && w30.by_family[key];
      if(fam7 || fam30){
        meta.append(text('span','7d: ~'+api.fmtUsd(fam7 && fam7.hypothetical_usd)+' · 30d: ~'+api.fmtUsd(fam30 && fam30.hypothetical_usd)+' ('+api.fmtTokens(fam30?fam30.total_tokens:0)+' tok)'));
      }
      card.append(top,meta);
      let pctVal = null;
      if(primary && primary.allowance && primary.allowance.windows && primary.allowance.windows.length){
        pctVal=Math.max(0,Math.min(100,Math.round(Number(primary.allowance.windows[0].remaining_percent||0))));
      } else if(typeof mon.remaining_percent === 'number'){
        pctVal=Math.max(0,Math.min(100,Math.round(Number(mon.remaining_percent))));
      }
      if(pctVal !== null){
        const meter=document.createElement('div');
        meter.className='provider-meter';
        meter.style.marginTop='6px';
        const fill=document.createElement('span');
        fill.style.width=pctVal+'%';
        meter.append(fill);
        card.append(meter);
      }
      card.onclick=()=>{family=key;connectionId=null;drawAccounts();drawDetail();};
      matrix.append(card);
    });
  }
  function drawAccounts(){
    $('provider-tabs').replaceChildren();Object.entries(api.labels).forEach(([key,label])=>{const b=button(label,()=>{family=key;connectionId=null;drawAccounts();drawDetail();});b.setAttribute('aria-pressed',String(key===family));$('provider-tabs').append(b);});
    const account=active();if(account)connectionId=account.id;
    $('provider-accounts').replaceChildren();data.connections.filter(c=>c.family===family).forEach(c=>{const b=button(c.name,()=>{connectionId=c.id;drawAccounts();drawDetail();});b.className='provider-account';b.setAttribute('aria-pressed',String(c.id===connectionId));b.append(text('span',c.mode+' · '+c.auth.replaceAll('_',' ')+' · allowance '+c.allowance.state));$('provider-accounts').append(b);});
    const cap=account && account.capability;
    $('add-account-limit').textContent=cap && !cap.isolated ? cap.limit || 'This installed CLI cannot verify isolated subscription homes. Optional API mode is separate and unready for execution.' : 'A second subscription uses a separate native home. The existing default is never overwritten.';
    $('add-account').disabled=false;
    drawWave2Matrix();
  }
  function drawDetail(){
    const c=active(),detail=$('provider-detail');detail.replaceChildren();if(!c)return;
    detail.append(text('h2',api.labels[c.family]+' · '+c.name),text('p','Runs on '+data.host.name+' · '+c.mode+' mode · '+(c.capability.installed?'CLI installed':'CLI unavailable')+' · version '+(c.capability.version||'Not reported')));
    if(c.capability.limit)detail.append(text('p',c.capability.limit,'setup-notice'));
    detail.append(text('p',c.execution.reason,'muted'));
    const label=text('label','Connection nickname');label.htmlFor='account-nickname';const nickname=document.createElement('input');nickname.id='account-nickname';nickname.value=c.name;nickname.maxLength=70;
    detail.append(label,nickname,button('Save nickname',async()=>{render(await api.request('/api/provider-setup/rename',{connection_id:c.id,name:nickname.value,expected_revision:data.settings_revision}));}));
    const actions=document.createElement('div');actions.className='setup-actions';
    actions.append(button('Refresh / test this account on host',()=>refresh(c.id)));
    if(c.mode==='subscription'){
      const sign=button('Sign in on mother ship',async()=>{await beginLogin(c.id);});
      sign.disabled=c.native_default || !c.capability.login || !c.capability.isolated || c.auth==='signed_in';sign.textContent=c.auth==='expired'?'Reconnect on mother ship':'Sign in on mother ship';actions.append(sign);
      if(c.native_default)detail.append(text('p','Existing native sign-in is retained. To enroll another subscription, add a named connection first. No open terminal is needed for a persisted login.','small muted'));
    }else{
      detail.append(text('p','API mode has separate billing. Credentials are stored in the host OS vault. Its model catalog test submits no model work. Execution remains unready.','setup-notice'));
      if(data.client_can_enter_api && data.api_storage_available){
        const l=text('label','API key · secure host storage');l.htmlFor='api-key';const input=document.createElement('input');input.id='api-key';input.type='password';input.autocomplete='off';
        detail.append(l,input,button('Validate & save API credential on host',async()=>{const key=input.value;input.value='';render(await api.request('/api/provider-setup/api-key',{connection_id:c.id,api_key:key}));}));
      }else detail.append(text('p','Enter API credentials in Setup on the mother ship itself. Secure storage must be available.','muted'));
    }
    if(!c.native_default)actions.append(button('Remove connection from Setup',async()=>{render(await api.request('/api/provider-setup/remove',{connection_id:c.id,expected_revision:data.settings_revision}));connectionId=null;drawAccounts();drawDetail();}));
    detail.append(actions);reportFacts(detail,c);const panel=document.createElement('div');panel.id='login-progress';detail.append(panel);drawLogin();
  }
  function reserveSignIn(){const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;return popup;}
  async function beginLogin(identity,popup){
    loginWindow=popup || reserveSignIn();openedLogin=null;
    try{login=await api.request('/api/provider-setup/login',{connection_id:identity});drawLogin();scheduleLogin();}
    catch(error){if(loginWindow && !loginWindow.closed)loginWindow.close();loginWindow=null;throw error;}
  }
  function drawLogin(){const box=$('login-progress');if(!box || !login || login.connection_id!==connectionId)return;box.replaceChildren(text('p',login.message,'setup-notice'));
    if(login.url && openedLogin!==login.id && loginWindow && !loginWindow.closed){loginWindow.location.replace(login.url);openedLogin=login.id;}
    if(['completed','failed','cancelled'].includes(login.state) && loginWindow && openedLogin!==login.id){loginWindow.close();loginWindow=null;}
    if(login.url){const link=text('a','Open native sign-in');link.href=login.url;link.target='_blank';link.rel='noopener noreferrer';box.append(link);}
    if(login.user_code)box.append(text('p','Native device code: '+login.user_code));
    if(['starting','awaiting_browser','cancelling'].includes(login.state)){box.append(text('p','This attempt expires at '+new Date(login.expires_at*1000).toLocaleTimeString()));const cancel=button('Cancel sign-in',async()=>{login=await api.request('/api/provider-setup/cancel',{id:login.id});drawLogin();});cancel.disabled=login.state==='cancelling';box.append(cancel);}
  }
  function scheduleLogin(){clearTimeout(poll);if(!login || !['starting','awaiting_browser','cancelling'].includes(login.state))return;poll=setTimeout(async()=>{try{login=await api.request('/api/provider-setup/login?id='+encodeURIComponent(login.id));drawLogin();if(login.state==='completed')render(await api.request('/api/provider-setup'));scheduleLogin();}catch(error){$('setup-message').textContent=error.message;}},1000);}
  function render(value){
    if(data && value.settings_revision<data.settings_revision)return;
    const preferences=data && controller && value.settings_revision===data.settings_revision ? {...controller.get(),warning_threshold:Number($('setup-threshold').value),warning_policy:$('setup-warning').value} : value.preferences;
    data=value;const first=!connectionId;family=first ? value.preferences.family || value.default_family : family;
    $('setup-host').textContent=value.host.name+' · mother ship';$('provider-host-note').textContent='All actions run on '+value.host.name+'. This browser is the host’s interface. Authentication and capacity are separate facts.';
    $('host-runtime').textContent='Connected runtime: '+value.host.name+' · '+(value.host.configured?'existing setup retained':'first setup')+' · data directory '+value.host.data_directory;
    $('host-network').textContent=value.host.tailscale;$('setup-project-roots').replaceChildren();value.host.project_roots.forEach(root=>$('setup-project-roots').append(text('li',root)));
    $('setup-initialize').hidden=!value.host.first_setup;
    if(!value.host.project_roots.length)$('setup-project-roots').append(text('li','No configured project folders were reported. Choose the first storage location with Aladdin in Star Chart.'));
    if(value.host.star_chart_url)$('setup-star-chart').href=value.host.star_chart_url;
    drawAccounts();drawDetail();controller=api.controls({...data,preferences},'setup-',()=>{});$('setup-threshold').value=String(preferences.warning_threshold);$('setup-warning').value=preferences.warning_policy;
    if(data.settings_error)$('setup-message').textContent=data.settings_error;
  }
  async function refresh(id){$('provider-refresh').disabled=true;$('refresh-message').textContent='Reading native status and account reports on the mother ship…';try{render(await api.request('/api/provider-setup?refresh=1'+(id?'&connection_id='+encodeURIComponent(id):'')));$('refresh-message').textContent='Host reads completed; unsupported reports remain explicit.';}finally{$('provider-refresh').disabled=false;}}

  // ── Wave 3 Star Chart & Workspace Onboarding Functions ─────────────────
  function syncWave3FromServer(){
    w3Synced=true;
    api.request('/api/steward/setup_chart').then(res=>{
      if(res && res.ok)applyWave3ServerState(res);
    }).catch(()=>{});
  }
  function applyWave3ServerState(stateObj){
    if(!stateObj || typeof stateObj!=='object')return;
    ['primary_root','external_roots','project_groups','folders','goal_tiles','pull_history','search_presets'].forEach(k=>{
      if(stateObj[k]!==undefined && stateObj[k]!==null)w3State[k]=stateObj[k];
    });
    renderWave3All();
  }
  function postWave3Action(payload){
    return api.request('/api/steward/setup_chart',payload).then(res=>{
      if(res && res.state)applyWave3ServerState(res.state);
      else renderWave3All();
      return res;
    }).catch(()=>{
      renderWave3All();
    });
  }
  function renderWave3PipelineBadges(){
    const folders=w3State.folders||[];
    const ext=w3State.external_roots||[];
    const groups=w3State.project_groups||[];
    const goals=w3State.goal_tiles||[];
    const activeCount=folders.filter(f=>f.role==='active').length;
    const subCount=folders.filter(f=>f.role==='subordinate').length;
    const exclCount=folders.filter(f=>f.role==='excluded').length;
    let cockpitCount=0;
    folders.forEach(f=>{cockpitCount+=(f.cockpits||[]).length;});
    if($('pipe-badge-1'))$('pipe-badge-1').textContent=(w3State.primary_root||'C:\\dev')+(ext.length?' + '+ext.length+' External':'');
    if($('pipe-badge-2'))$('pipe-badge-2').textContent=activeCount+' Active · '+subCount+' Sub · '+exclCount+' Excl';
    if($('pipe-badge-3'))$('pipe-badge-3').textContent=groups.length+' Groups · '+cockpitCount+' Cockpits';
    if($('pipe-badge-4'))$('pipe-badge-4').textContent=goals.length+' Campaign Acts';
    if($('rail-status-chart'))$('rail-status-chart').textContent=activeCount+' Active Roots · '+goals.length+' Acts';
  }
  function renderWave3RootBar(){
    if($('root-path-display'))$('root-path-display').textContent=w3State.primary_root||'C:\\dev';
    const extList=$('external-roots-pills');
    if(!extList)return;
    extList.replaceChildren();
    (w3State.external_roots||[]).forEach(ext=>{
      const pill=document.createElement('span');
      pill.className='w3-ext-pill';
      pill.append(text('span','🔗 '+(ext.label||'External')+': '),text('code',ext.path));
      const unlink=text('button','Unlink','btn-mini');
      unlink.type='button';
      unlink.onclick=()=>{
        w3State.external_roots=(w3State.external_roots||[]).filter(e=>e.id!==ext.id);
        w3State.folders=(w3State.folders||[]).filter(f=>!(f.source==='external' && String(f.path).toLowerCase()===String(ext.path).toLowerCase()));
        postWave3Action({action:'unlink_external',id:ext.id,path:ext.path});
      };
      pill.append(unlink);
      extList.append(pill);
    });
  }
  function renderWave3SearchPullDrawer(){
    const resBox=$('search-pull-results');
    if(resBox){
      resBox.replaceChildren();
      const presets=(w3State.search_presets && w3State.search_presets[w3ActivePreset])||[];
      const q=($('input-search-pull')?$('input-search-pull').value:'').trim().toLowerCase();
      const filtered=presets.filter(it=>!q || (it.name+' '+it.src+' '+it.matchReason).toLowerCase().includes(q));
      if(!filtered.length){
        resBox.append(text('p','No external candidate folders matched that filter.','muted small'));
      }else{
        filtered.forEach(cand=>{
          const card=document.createElement('div');
          card.className='w3-search-card';
          const destFull=(w3State.primary_root||'C:\\dev').replace(/[\\/]$/,'')+'\\'+cand.destSubpath;
          const info=document.createElement('div');
          info.append(
            text('strong',cand.name+' '),
            text('span',cand.files+' files · '+cand.size,'w3-badge w3-badge-sky'),
            text('div','Source: '+cand.src+' → Copy to: '+destFull,'w3-folder-path'),
            text('div',cand.matchReason+' · '+cand.age,'muted small')
          );
          const copyBtn=text('button','📥 Copy into '+(w3State.primary_root||'C:\\dev'),'primary');
          copyBtn.type='button';
          copyBtn.onclick=()=>{
            postWave3Action({
              action:'search_pull_copy',
              candidateId:cand.id,
              name:cand.name,
              src:cand.src,
              destSubpath:cand.destSubpath,
              files:cand.files,
              size:cand.size,
              groupId:cand.suggestedGroup||'grp-core'
            });
          };
          card.append(info,copyBtn);
          resBox.append(card);
        });
      }
    }
    const undoBox=$('pull-undo-list');
    if(undoBox){
      undoBox.replaceChildren();
      const activePulls=(w3State.pull_history||[]).filter(p=>!p.undone);
      if(!activePulls.length){
        undoBox.append(text('p','No active pulls in this session.','muted small'));
      }else{
        activePulls.forEach(p=>{
          const row=document.createElement('div');
          row.className='w3-pull-item';
          row.append(text('span',p.src+' → '+p.dest+' ('+p.files+' files · SHA-256 '+p.sha256+')','small'));
          const undoBtn=text('button','↩ Undo Copy','btn-mini');
          undoBtn.type='button';
          undoBtn.onclick=()=>{
            p.undone=true;
            postWave3Action({action:'search_pull_undo',pullId:p.id});
          };
          row.append(undoBtn);
          undoBox.append(row);
        });
      }
    }
  }
  function changeFolderRole(folderId,newRole){
    const folders=w3State.folders||[];
    const target=folders.find(f=>f.id===folderId);
    if(!target || target.role===newRole)return;
    const prevRole=target.role,prevParent=target.parentId;
    target.role=newRole;
    if(newRole==='subordinate'){
      const firstActive=folders.find(f=>f.id!==folderId && f.role==='active');
      target.parentId=firstActive?firstActive.id:null;
      if(firstActive && firstActive.groupId)target.groupId=firstActive.groupId;
    }else{
      target.parentId=null;
    }
    if(newRole==='excluded'){
      w3LastExcludedUndo={folderId,name:target.name,prevRole,prevParent};
      if($('exclude-undo-toast') && $('exclude-undo-text')){
        $('exclude-undo-toast').hidden=false;
        $('exclude-undo-text').textContent='Moved "'+target.name+'" to Excluded (bottom tray).';
      }
    }
    postWave3Action({action:'set_folder_role',folderId,role:newRole,parentId:target.parentId});
  }
  function renderWave3FolderRow(folder,activeParents,groupsById){
    const row=document.createElement('div');
    row.className='w3-folder-row is-'+folder.role+'-role';
    row.setAttribute('data-folder-id',folder.id);
    if(folder.role!=='excluded'){
      row.setAttribute('draggable','true');
      row.addEventListener('dragstart',ev=>{
        w3DraggedFolderId=folder.id;
        if(ev.dataTransfer)ev.dataTransfer.setData('text/plain',folder.id);
      });
    }
    const top=document.createElement('div');
    top.className='w3-folder-top';
    const left=document.createElement('div');
    const titleLine=document.createElement('div');
    titleLine.className='w3-folder-title';
    titleLine.append(
      text('span',folder.role==='active'?'★':(folder.role==='subordinate'?'↳':'○')),
      text('strong',folder.name)
    );
    if(folder.source==='external'){
      titleLine.append(text('span','External Link','w3-badge w3-badge-purple'));
    }
    const grp=groupsById[folder.groupId];
    if(grp && folder.role!=='excluded'){
      titleLine.append(text('span',grp.icon+' '+grp.name,'w3-badge w3-badge-emerald'));
    }
    const pathLine=text('div',folder.path+' · git:'+(folder.gitBranch||'main')+' · '+(folder.filesCount||0)+' files','w3-folder-path');
    left.append(titleLine,pathLine);

    const seg=document.createElement('div');
    seg.className='role-seg-group';
    [['active','★ Active'],['subordinate','↳ Subordinate'],['excluded','○ Excluded']].forEach(([key,lbl])=>{
      const b=text('button',lbl,'role-seg-btn'+(folder.role===key?' is-selected-'+key:''));
      b.type='button';
      b.onclick=()=>changeFolderRole(folder.id,key);
      seg.append(b);
    });
    top.append(left,seg);
    row.append(top);

    if(folder.role==='subordinate'){
      const subBar=document.createElement('div');
      subBar.className='w3-subordinate-bar';
      subBar.append(text('span','↳ Subordinate helper/library under parent:'));
      const sel=document.createElement('select');
      sel.className='subordinate-parent-select';
      activeParents.forEach(p=>{
        if(p.id===folder.id)return;
        const opt=text('option',p.name+' ('+p.path+')');
        opt.value=p.id;
        opt.selected=p.id===folder.parentId;
        sel.append(opt);
      });
      sel.onchange=()=>{
        folder.parentId=sel.value;
        const parentObj=activeParents.find(p=>p.id===sel.value);
        if(parentObj && parentObj.groupId)folder.groupId=parentObj.groupId;
        postWave3Action({action:'set_folder_parent',folderId:folder.id,parentId:sel.value});
      };
      subBar.append(sel);
      row.append(subBar);
    }
    if(folder.liveWork){
      row.append(text('div',
        folder.role==='excluded'
          ? '⚠ Live work preserved ('+(folder.liveWorkDetail||'active session')+') — excluding only hides from Star Chart indexing; running processes & files are untouched.'
          : '⚡ Live: '+(folder.liveWorkDetail||'Active Steward session'),
        'w3-livework-guard'
      ));
    }
    return row;
  }
  function renderWave3FoldersList(){
    const container=$('folder-list-container');
    if(!container)return;
    container.replaceChildren();
    const folders=w3State.folders||[];
    const groupsById={};
    (w3State.project_groups||[]).forEach(g=>{groupsById[g.id]=g;});
    const activeParents=folders.filter(f=>f.role==='active');
    const matches=f=>{
      if(w3RoleFilter!=='all' && f.role!==w3RoleFilter)return false;
      if(!w3SearchFilter)return true;
      return (f.name+' '+f.path+' '+(f.desc||'')).toLowerCase().includes(w3SearchFilter);
    };
    const topZone=[],visitedSub={};
    folders.forEach(f=>{
      if(f.role==='active'){
        if(matches(f))topZone.push(f);
        folders.forEach(sub=>{
          if(sub.role==='subordinate' && sub.parentId===f.id){
            visitedSub[sub.id]=true;
            if(matches(sub))topZone.push(sub);
          }
        });
      }
    });
    folders.forEach(sub=>{
      if(sub.role==='subordinate' && !visitedSub[sub.id] && matches(sub))topZone.push(sub);
    });
    const bottomExcluded=folders.filter(f=>f.role==='excluded' && matches(f));

    const topHdr=document.createElement('div');
    topHdr.className='w3-zone-header';
    topHdr.append(text('span','▲ INDEXED WORKSPACE ROOTS (★ ACTIVE & ↳ SUBORDINATE)'),text('span',topZone.length+' shown'));
    container.append(topHdr);
    topZone.forEach(f=>container.append(renderWave3FolderRow(f,activeParents,groupsById)));

    if(bottomExcluded.length){
      const tray=document.createElement('div');
      tray.className='w3-excluded-tray';
      const exHdr=document.createElement('div');
      exHdr.className='w3-zone-header';
      exHdr.append(text('span','▼ EXCLUDED — NOT INDEXED IN STAR CHART'),text('span',bottomExcluded.length+' excluded'));
      tray.append(exHdr);
      bottomExcluded.forEach(f=>tray.append(renderWave3FolderRow(f,activeParents,groupsById)));
      container.append(tray);
    }
  }
  function renderWave3ProjectsMode(){
    const grid=$('projects-grid-container');
    if(!grid)return;
    grid.replaceChildren();
    const groups=w3State.project_groups||[];
    const folders=w3State.folders||[];
    const srcSel=$('sel-combine-src'),dstSel=$('sel-combine-dst');
    if(srcSel && dstSel){
      srcSel.replaceChildren();dstSel.replaceChildren();
      groups.forEach((g,idx)=>{
        const o1=text('option',g.name);o1.value=g.id;if(idx===groups.length-1)o1.selected=true;srcSel.append(o1);
        const o2=text('option',g.name);o2.value=g.id;if(idx===0)o2.selected=true;dstSel.append(o2);
      });
    }
    groups.forEach(grp=>{
      const card=document.createElement('div');
      card.className='w3-project-card';
      card.setAttribute('data-group-id',grp.id);
      card.addEventListener('dragover',ev=>{ev.preventDefault();card.classList.add('is-drop-hover');});
      card.addEventListener('dragleave',()=>card.classList.remove('is-drop-hover'));
      card.addEventListener('drop',ev=>{
        ev.preventDefault();card.classList.remove('is-drop-hover');
        const fid=(ev.dataTransfer && ev.dataTransfer.getData('text/plain'))||w3DraggedFolderId;
        const f=folders.find(x=>x.id===fid);
        if(f){f.groupId=grp.id;postWave3Action({action:'set_project_group',folderId:fid,groupId:grp.id});}
      });
      const groupFolders=folders.filter(f=>f.role!=='excluded' && f.groupId===grp.id);
      const top=document.createElement('div');
      top.className='w3-card-top';
      const titleBox=document.createElement('div');
      titleBox.append(text('h4',(grp.icon||'📁')+' '+grp.name),text('p',grp.desc||'','muted small'));
      const addCpBtn=text('button','+ Add AI Cockpit','btn-mini');
      addCpBtn.type='button';
      top.append(titleBox,addCpBtn);
      card.append(top);

      const chips=document.createElement('div');
      chips.className='w3-folder-chips';
      if(!groupFolders.length){
        chips.append(text('span','Drag a folder here or assign below','muted small'));
      }else{
        groupFolders.forEach(f=>{
          chips.append(text('span',(f.role==='subordinate'?'↳ ':'★ ')+f.name+' ('+f.path+')','w3-folder-chip'+(f.role==='subordinate'?' is-sub':'')));
        });
      }
      card.append(chips);

      const cpForm=document.createElement('div');
      cpForm.className='w3-inline-form';
      cpForm.hidden=true;
      const cpName=document.createElement('input');
      cpName.type='text';cpName.placeholder='Cockpit title (e.g. Crucible Plan Shark)';
      const cpEng=document.createElement('select');
      ['claude-fable-5-1 · max','gemini-4-argon · high','gpt-6.1-sol · ultra','grok-4.7 · xhigh'].forEach(eng=>{const o=text('option',eng);o.value=eng;cpEng.append(o);});
      const cpSave=text('button','Save Cockpit','primary btn-mini');
      cpSave.type='button';
      cpSave.onclick=()=>{
        const tf=groupFolders[0]||folders.find(f=>f.role==='active');
        if(!tf || !cpName.value.trim())return;
        tf.cockpits=tf.cockpits||[];
        tf.cockpits.push({id:'cp-'+Date.now(),name:cpName.value.trim(),engine:cpEng.value,status:'Drafted'});
        postWave3Action({action:'add_cockpit',folderId:tf.id,name:cpName.value.trim(),engine:cpEng.value,status:'Drafted'});
      };
      const cpRow=document.createElement('div');
      cpRow.className='w3-form-row';
      cpRow.append(cpName,cpEng,cpSave);
      cpForm.append(cpRow);
      card.append(cpForm);
      addCpBtn.onclick=()=>{cpForm.hidden=!cpForm.hidden;};

      const cpList=document.createElement('div');
      cpList.className='w3-cockpit-list';
      groupFolders.forEach(f=>{
        (f.cockpits||[]).forEach(cp=>{
          const item=document.createElement('div');
          item.className='w3-cockpit-item';
          item.append(text('span','🖥 '+cp.name+' ('+f.name+')'),text('span',cp.engine+' · '+cp.status,'w3-badge w3-badge-sky'));
          cpList.append(item);
        });
      });
      if(cpList.children.length)card.append(cpList);
      grid.append(card);
    });
  }
  function renderWave3StarChartMode(){
    const grid=$('goals-grid-container');
    if(!grid)return;
    grid.replaceChildren();
    const goals=w3State.goal_tiles||[];
    const groups=w3State.project_groups||[];
    const groupsById={};
    groups.forEach(g=>{groupsById[g.id]=g;});
    ['sel-goal-group','sel-shaper-group'].forEach(selId=>{
      const s=$(selId);if(!s)return;
      s.replaceChildren();
      groups.forEach(g=>{const o=text('option',g.icon+' '+g.name);o.value=g.id;s.append(o);});
    });
    const gSrc=$('sel-combine-goal-src'),gDst=$('sel-combine-goal-dst');
    if(gSrc && gDst){
      gSrc.replaceChildren();gDst.replaceChildren();
      goals.forEach((g,idx)=>{
        const o1=text('option',g.act+' — '+g.title);o1.value=g.id;if(idx===goals.length-1)o1.selected=true;gSrc.append(o1);
        const o2=text('option',g.act+' — '+g.title);o2.value=g.id;if(idx===0)o2.selected=true;gDst.append(o2);
      });
    }
    goals.forEach(goal=>{
      const card=document.createElement('div');
      card.className='w3-goal-card';
      card.setAttribute('data-goal-id',goal.id);
      const linkedGrp=groupsById[goal.linkedGroup];
      const top=document.createElement('div');
      top.className='w3-card-top';
      const left=document.createElement('div');
      left.append(
        text('p',goal.act+' · '+(goal.horizon||'2026'),'eyebrow'),
        text('h4',goal.title),
        text('p',goal.desc||'','muted small')
      );
      const badges=document.createElement('div');
      badges.className='w3-toolbar-btns';
      badges.append(text('span',goal.status||'Active','w3-badge w3-badge-amber'));
      if(linkedGrp)badges.append(text('span',linkedGrp.icon+' '+linkedGrp.name,'w3-badge w3-badge-emerald'));
      top.append(left,badges);
      card.append(top);

      const msList=document.createElement('ul');
      msList.className='w3-milestone-list';
      (goal.milestones||[]).forEach(ms=>{
        const li=document.createElement('li');
        li.className='w3-milestone-item';
        const chk=document.createElement('input');
        chk.type='checkbox';chk.checked=Boolean(ms.done);
        const sp=text('span',ms.text);
        if(ms.done)sp.style.textDecoration='line-through';
        chk.onchange=()=>{
          ms.done=chk.checked;
          postWave3Action({action:'update_goal_tile',goalId:goal.id,milestones:goal.milestones});
        };
        li.append(chk,sp);
        msList.append(li);
      });
      card.append(msList);
      grid.append(card);
    });
  }
  function switchWave3Mode(mode){
    ['projects','starchart','guide'].forEach(m=>{
      const tab=$('tab-mode-'+m),view=$('view-mode-'+m);
      if(tab)tab.classList.toggle('is-active',m===mode);
      if(view)view.hidden=m!==mode;
    });
  }
  function renderWave3All(){
    renderWave3PipelineBadges();
    renderWave3RootBar();
    renderWave3SearchPullDrawer();
    renderWave3FoldersList();
    renderWave3ProjectsMode();
    renderWave3StarChartMode();
  }

  // ── Wire Event Listeners ───────────────────────────────────────────────
  document.querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>section(b.dataset.section));
  document.querySelectorAll('.cave-rail-stage').forEach(b=>b.onclick=()=>section(b.getAttribute('data-rail-section')));
  const personaLabels={aladdin:'Aladdin · Cave of Wonders',jarvis:'Jarvis · The Helm',ecgberht:'Ecgberht · The High Seat'};
  document.querySelectorAll('[data-persona-choice]').forEach(btn=>{
    btn.onclick=()=>{
      const p=btn.getAttribute('data-persona-choice')||'aladdin';
      document.querySelectorAll('[data-persona-choice]').forEach(b=>b.classList.toggle('is-active',b===btn));
      if($('persona-active-badge'))$('persona-active-badge').textContent=personaLabels[p]||p;
      try{localStorage.setItem('anchor_steward_persona',p);}catch(e){}
      api.request('/api/settings',{steward_type:p}).catch(()=>{});
    };
  });
  $('setup-return').onclick=leave;$('chart-return').onclick=leave;$('new-account-mode').onchange=drawAccounts;
  $('provider-refresh').onclick=()=>refresh().catch(error=>$('setup-message').textContent=error.message);
  $('setup-initialize').onclick=async()=>{try{render(await api.request('/api/provider-setup/initialize',{expected_revision:data.settings_revision}));$('initialize-message').textContent='Setup saved with Aladdin. Existing installation and folders retained.';section('providers');}catch(error){$('initialize-message').textContent=error.message;}};
  $('add-account-form').onsubmit=async event=>{
    event.preventDefault();const mode=$('new-account-mode').value,cap=active() && active().capability;
    const popup=mode==='subscription' && cap && cap.login && cap.isolated ? reserveSignIn() : null;
    $('add-account').disabled=true;
    $('provider-detail').replaceChildren(text('p','Adding named connection on the mother ship…','setup-notice'));
    try{const result=await api.request('/api/provider-setup/accounts',{family,name:$('new-account-name').value,mode,expected_revision:data.settings_revision});connectionId=result.connection_id;render(result.snapshot);$('new-account-name').value='';if(mode==='subscription')await beginLogin(connectionId,popup);}
    catch(error){if(popup && !popup.closed)popup.close();drawDetail();$('setup-message').textContent=error.message;}
    finally{$('add-account').disabled=false;}
  };
  $('setup-apply').onclick=async()=>{$('setup-apply').disabled=true;$('apply-message').textContent='Saving…';try{const prefs=controller.get();prefs.warning_threshold=Number($('setup-threshold').value);prefs.warning_policy=$('setup-warning').value;render(await api.request('/api/provider-setup/apply',{preferences:prefs,expected_revision:data.settings_revision}));$('apply-message').textContent='Saved for new work. Existing conversations retain their accounts and sessions.';if(window.parent!==window)window.parent.postMessage({type:'anchor-setup-saved'},location.origin);}catch(error){$('apply-message').textContent=error.message;}finally{$('setup-apply').disabled=false;}};

  // Wave 3 Controls
  function toggleDrawer(id){
    ['drawer-change-root','drawer-add-external','drawer-search-pull'].forEach(dId=>{
      const node=$(dId);if(!node)return;
      node.hidden=dId===id?!node.hidden:true;
    });
  }
  if($('btn-toggle-change-root'))$('btn-toggle-change-root').onclick=()=>toggleDrawer('drawer-change-root');
  if($('btn-toggle-add-external'))$('btn-toggle-add-external').onclick=()=>toggleDrawer('drawer-add-external');
  if($('btn-toggle-search-pull'))$('btn-toggle-search-pull').onclick=()=>toggleDrawer('drawer-search-pull');
  document.querySelectorAll('[data-close-drawer]').forEach(btn=>{btn.onclick=()=>{const d=$(btn.getAttribute('data-close-drawer'));if(d)d.hidden=true;};});
  if($('btn-apply-root'))$('btn-apply-root').onclick=()=>{
    const newRoot=($('input-new-root').value||'').trim();
    if(!newRoot)return;
    w3State.primary_root=newRoot;
    if($('drawer-change-root'))$('drawer-change-root').hidden=true;
    postWave3Action({action:'set_root',path:newRoot,create_if_missing:Boolean($('chk-create-root')&&$('chk-create-root').checked)});
  };
  if($('btn-attach-external'))$('btn-attach-external').onclick=()=>{
    const extPath=($('input-ext-path').value||'').trim();
    const mode=$('sel-ext-mode')?$('sel-ext-mode').value:'read_write';
    if(!extPath)return;
    $('input-ext-path').value='';
    if($('drawer-add-external'))$('drawer-add-external').hidden=true;
    postWave3Action({action:'add_external',path:extPath,mode});
  };
  document.querySelectorAll('[data-search-preset]').forEach(btn=>{
    btn.onclick=()=>{
      w3ActivePreset=btn.getAttribute('data-search-preset')||'recent';
      document.querySelectorAll('[data-search-preset]').forEach(b=>b.classList.toggle('is-active',b===btn));
      renderWave3SearchPullDrawer();
    };
  });
  if($('btn-run-search'))$('btn-run-search').onclick=renderWave3SearchPullDrawer;
  if($('input-search-pull'))$('input-search-pull').oninput=renderWave3SearchPullDrawer;
  if($('input-folder-filter'))$('input-folder-filter').oninput=ev=>{w3SearchFilter=(ev.target.value||'').trim().toLowerCase();renderWave3FoldersList();};
  document.querySelectorAll('[data-role-filter]').forEach(btn=>{
    btn.onclick=()=>{
      w3RoleFilter=btn.getAttribute('data-role-filter')||'all';
      document.querySelectorAll('[data-role-filter]').forEach(b=>b.classList.toggle('is-active',b===btn));
      renderWave3FoldersList();
    };
  });
  if($('btn-undo-exclude'))$('btn-undo-exclude').onclick=()=>{
    if(!w3LastExcludedUndo)return;
    const u=w3LastExcludedUndo;w3LastExcludedUndo=null;
    if($('exclude-undo-toast'))$('exclude-undo-toast').hidden=true;
    const f=(w3State.folders||[]).find(x=>x.id===u.folderId);
    if(f){f.role=u.prevRole||'active';f.parentId=u.prevParent||null;}
    postWave3Action({action:'set_folder_role',folderId:u.folderId,role:u.prevRole||'active',parentId:u.prevParent||null});
  };
  document.querySelectorAll('[data-w3-mode]').forEach(btn=>{btn.onclick=()=>switchWave3Mode(btn.getAttribute('data-w3-mode'));});
  document.querySelectorAll('[data-close-inline]').forEach(btn=>{btn.onclick=()=>{const n=$(btn.getAttribute('data-close-inline'));if(n)n.hidden=true;};});
  if($('btn-auto-group'))$('btn-auto-group').onclick=()=>postWave3Action({action:'auto_group'});
  if($('btn-open-new-group'))$('btn-open-new-group').onclick=()=>{const f=$('form-new-group');if(f)f.hidden=!f.hidden;};
  if($('btn-save-new-group'))$('btn-save-new-group').onclick=()=>{
    const name=($('input-new-group-name').value||'').trim(),desc=($('input-new-group-desc').value||'').trim();
    if(!name)return;
    $('input-new-group-name').value='';$('input-new-group-desc').value='';
    if($('form-new-group'))$('form-new-group').hidden=true;
    postWave3Action({action:'create_group',name,desc});
  };
  if($('btn-open-combine-groups'))$('btn-open-combine-groups').onclick=()=>{const f=$('form-combine-groups');if(f)f.hidden=!f.hidden;};
  if($('btn-confirm-combine-groups'))$('btn-confirm-combine-groups').onclick=()=>{
    const src=$('sel-combine-src')?$('sel-combine-src').value:'',dst=$('sel-combine-dst')?$('sel-combine-dst').value:'';
    if(!src || !dst || src===dst)return;
    if($('form-combine-groups'))$('form-combine-groups').hidden=true;
    postWave3Action({action:'combine_groups',sourceGroupId:src,targetGroupId:dst});
  };
  if($('btn-open-goal-shaper'))$('btn-open-goal-shaper').onclick=()=>{const d=$('drawer-goal-shaper');if(d)d.hidden=!d.hidden;};
  if($('btn-generate-shaped-goals'))$('btn-generate-shaped-goals').onclick=()=>{
    const rawText=($('input-goal-shaper').value||'').trim(),linkedGroup=$('sel-shaper-group')?$('sel-shaper-group').value:'grp-core';
    if(!rawText)return;
    $('input-goal-shaper').value='';
    if($('drawer-goal-shaper'))$('drawer-goal-shaper').hidden=true;
    postWave3Action({action:'shape_goals',rawText,linkedGroup});
  };
  if($('btn-open-new-goal'))$('btn-open-new-goal').onclick=()=>{const f=$('form-new-goal');if(f)f.hidden=!f.hidden;};
  if($('btn-save-new-goal'))$('btn-save-new-goal').onclick=()=>{
    const act=($('input-goal-act').value||'').trim()||'ACT IV · STRATEGIC INITIATIVE';
    const horizon=($('input-goal-horizon').value||'').trim()||'Q4 2026';
    const linkedGroup=$('sel-goal-group')?$('sel-goal-group').value:'grp-core';
    const title=($('input-goal-title').value||'').trim(),desc=($('input-goal-desc').value||'').trim();
    if(!title)return;
    $('input-goal-title').value='';$('input-goal-desc').value='';
    if($('form-new-goal'))$('form-new-goal').hidden=true;
    postWave3Action({action:'add_goal_tile',act,horizon,linkedGroup,title,desc});
  };
  if($('btn-open-combine-goals'))$('btn-open-combine-goals').onclick=()=>{const f=$('form-combine-goals');if(f)f.hidden=!f.hidden;};
  if($('btn-confirm-combine-goals'))$('btn-confirm-combine-goals').onclick=()=>{
    const src=$('sel-combine-goal-src')?$('sel-combine-goal-src').value:'',dst=$('sel-combine-goal-dst')?$('sel-combine-goal-dst').value:'';
    if(!src || !dst || src===dst)return;
    if($('form-combine-goals'))$('form-combine-goals').hidden=true;
    postWave3Action({action:'combine_goal_tiles',sourceGoalId:src,targetGoalId:dst});
  };
  document.querySelectorAll('[data-coach-focus]').forEach(btn=>{
    btn.onclick=()=>{
      const t=$(btn.getAttribute('data-coach-focus'));
      if(t)t.scrollIntoView({behavior:'smooth',block:'center'});
    };
  });
  document.querySelectorAll('[data-coach-switch-mode]').forEach(btn=>{
    btn.onclick=()=>switchWave3Mode(btn.getAttribute('data-coach-switch-mode'));
  });

  // ── Wave 9 / Stage 4: Calendar & Email Connectors ───────────────────────
  const COMMS_PRESETS={
    gmail:{label:'Primary Gmail & Calendar',imap_host:'imap.gmail.com',imap_port:993,auth_mode:'app_password',email_ph:'researcher@example.com',ics_ph:'https://calendar.google.com/calendar/ical/example/private/basic.ics',hint:'Use a 16-character Google App Password (or OAuth token) for read-only IMAP header sync, plus your private ICS feed URL for Google Calendar.'},
    outlook:{label:'Microsoft 365 & Exchange Calendar',imap_host:'outlook.office365.com',imap_port:993,auth_mode:'oauth_token',email_ph:'faculty@example.org',ics_ph:'https://outlook.office365.com/owa/calendar/example/reachcalendar.ics',hint:'Use a Microsoft 365 App Password or OAuth bearer token for Outlook read-only header sync, plus your published Outlook ICS calendar URL.'},
    custom:{label:'Custom Institutional IMAP & ICS',imap_host:'mail.example.org',imap_port:993,auth_mode:'app_password',email_ph:'counsel@example.org',ics_ph:'https://cal.example.org/dav/calendars/user/personal/?export',hint:'Connect any standard TLS IMAP server (port 993) and any RFC 5545 ICS or CalDAV export URL.'}
  };
  let w9CommsState=null;

  function applyCommsPreset(fam){
    const p=COMMS_PRESETS[fam]||COMMS_PRESETS.gmail;
    if($('comms-family'))$('comms-family').value=fam;
    if($('comms-label'))$('comms-label').value=p.label;
    if($('comms-imap-host'))$('comms-imap-host').value=p.imap_host;
    if($('comms-imap-port'))$('comms-imap-port').value=String(p.imap_port);
    if($('comms-auth-mode'))$('comms-auth-mode').value=p.auth_mode;
    if($('comms-email'))$('comms-email').placeholder=p.email_ph;
    if($('comms-ics-url'))$('comms-ics-url').placeholder=p.ics_ph;
    if($('comms-form-hint'))$('comms-form-hint').textContent=p.hint;
    document.querySelectorAll('.comms-preset-card').forEach(c=>c.classList.toggle('is-selected',c.getAttribute('data-comms-preset')===fam));
  }

  function renderWave9Comms(state){
    if(!state)return;
    w9CommsState=state;
    const accList=$('comms-accounts-list');
    const prevList=$('comms-reconciled-preview');
    const railSub=$('rail-status-comms');
    const accounts=state.accounts||[];
    if(railSub){
      railSub.textContent=accounts.length ? (accounts.length+' connected · OS Vault') : 'Gmail · Outlook · IMAP/ICS';
    }
    if(accList){
      accList.replaceChildren();
      if(!accounts.length){
        const empty=text('p','No external email/calendar account saved yet. Roadmap reconciliation is active across your local projects; use the form on the left to store a Gmail, Outlook, or Custom IMAP/ICS credential in the Windows OS Vault.','muted small');
        accList.append(empty);
      }else{
        accounts.forEach(a=>{
          const row=document.createElement('div');
          row.className='w3-folder-item';
          row.style.marginBottom='8px';
          const top=document.createElement('div');
          top.className='wave2-matrix-top';
          top.append(
            text('strong',(a.label||a.family||'Account')+' ('+(a.email||'ICS only')+')'),
            text('span',a.has_credential?'✓ OS Vault':'Configured','w3-badge '+(a.has_credential?'w3-badge-emerald':'w3-badge-amber'))
          );
          const meta=text('div',(a.imap_host?('IMAP '+a.imap_host+':'+a.imap_port+' · '):'')+(a.credential_storage||'OS Vault')+(a.ics_url?' · ICS feed linked':''),'muted small');
          const rmBtn=button('Remove',async()=>{
            const next=await api.request('/api/steward/comms',{action:'remove_account',id:a.id});
            renderWave9Comms(next);
          });
          rmBtn.className='btn-mini';
          top.append(rmBtn);
          row.append(top,meta);
          accList.append(row);
        });
      }
    }
    if(prevList){
      prevList.replaceChildren();
      const threads=(state.email_threads||[]).slice(0,4);
      const events=(state.calendar_events||[]).slice(0,3);
      events.forEach(ev=>{
        const item=document.createElement('div');
        item.className='w3-folder-item';
        item.style.marginBottom='6px';
        item.append(
          text('div','📅 '+ev.date+' ('+ev.time_label+') — '+ev.title,'small'),
          text('div','Project: '+(ev.project_name||'Calendar')+' · Source: '+ev.badge,'muted small')
        );
        prevList.append(item);
      });
      threads.forEach(th=>{
        const item=document.createElement('div');
        item.className='w3-folder-item';
        item.style.marginBottom='6px';
        item.append(
          text('div','✉ '+th.subject+' · '+th.badge,'small'),
          text('div',th.project_name+' — '+th.summary,'muted small')
        );
        prevList.append(item);
      });
    }
  }

  async function syncWave9CommsFromServer(){
    try{
      const st=await api.request('/api/steward/comms');
      renderWave9Comms(st);
    }catch(e){
      if($('comms-form-feedback'))$('comms-form-feedback').textContent=e.message;
    }
  }

  document.querySelectorAll('[data-select-comms-preset]').forEach(btn=>{
    btn.onclick=()=>applyCommsPreset(btn.getAttribute('data-select-comms-preset')||'gmail');
  });
  if($('comms-family'))$('comms-family').onchange=e=>applyCommsPreset(e.target.value);
  if($('comms-return'))$('comms-return').onclick=leave;
  if($('btn-comms-save-account'))$('btn-comms-save-account').onclick=async()=>{
    const fb=$('comms-form-feedback');
    if(fb)fb.textContent='Saving to OS Credential Vault…';
    try{
      const res=await api.request('/api/steward/comms',{
        action:'save_account',
        family:$('comms-family')?$('comms-family').value:'gmail',
        label:$('comms-label')?$('comms-label').value:'',
        email:$('comms-email')?$('comms-email').value:'',
        auth_mode:$('comms-auth-mode')?$('comms-auth-mode').value:'app_password',
        imap_host:$('comms-imap-host')?$('comms-imap-host').value:'',
        imap_port:$('comms-imap-port')?Number($('comms-imap-port').value||993):993,
        secret:$('comms-secret')?$('comms-secret').value:'',
        ics_url:$('comms-ics-url')?$('comms-ics-url').value:''
      });
      if($('comms-secret'))$('comms-secret').value='';
      renderWave9Comms(res);
      if(fb)fb.textContent='✓ Saved account configuration and stored secret in OS Credential Vault.';
    }catch(e){
      if(fb)fb.textContent='Error: '+e.message;
    }
  };
  if($('btn-comms-test-account'))$('btn-comms-test-account').onclick=async()=>{
    const fb=$('comms-form-feedback');
    if(fb)fb.textContent='Testing connection…';
    try{
      const res=await api.request('/api/steward/comms',{
        action:'test_account',
        family:$('comms-family')?$('comms-family').value:'gmail',
        email:$('comms-email')?$('comms-email').value:'',
        auth_mode:$('comms-auth-mode')?$('comms-auth-mode').value:'app_password',
        imap_host:$('comms-imap-host')?$('comms-imap-host').value:'',
        imap_port:$('comms-imap-port')?Number($('comms-imap-port').value||993):993,
        secret:$('comms-secret')?$('comms-secret').value:'',
        ics_url:$('comms-ics-url')?$('comms-ics-url').value:''
      });
      if(fb)fb.textContent=(res.test_ok?'✓ ':'ℹ ')+(res.summary||'Connection test completed.');
    }catch(e){
      if(fb)fb.textContent='Error: '+e.message;
    }
  };
  if($('btn-comms-sync-now'))$('btn-comms-sync-now').onclick=async()=>{
    const fb=$('comms-form-feedback');
    if(fb)fb.textContent='Syncing Calendar & Email and reconciling with project roadmaps…';
    try{
      const res=await api.request('/api/steward/comms',{action:'sync_now'});
      renderWave9Comms(res);
      if(fb)fb.textContent='✓ '+(res.sync_receipt||'Sync complete.');
    }catch(e){
      if(fb)fb.textContent='Error: '+e.message;
    }
  };
  if($('btn-comms-oauth-pkce'))$('btn-comms-oauth-pkce').onclick=async()=>{
    const fb=$('comms-form-feedback');
    const fam=$('comms-family')?$('comms-family').value:'gmail';
    const email=$('comms-email')?$('comms-email').value:'';
    if(fb)fb.textContent='Generating RFC 7636 OAuth2 PKCE S256 challenge…';
    try{
      const res=await api.request('/api/steward/comms',{action:'oauth_pkce_start',family:fam,email:email});
      if(res.pkce && res.pkce.authorize_url){
        if($('comms-auth-mode'))$('comms-auth-mode').value='oauth_token';
        if(fb)fb.innerHTML='✓ OAuth2 PKCE S256 challenge ready (code_challenge: <code>'+String(res.pkce.code_challenge||'').slice(0,18)+'…</code>). <a href="'+res.pkce.authorize_url+'" target="_blank" rel="noopener">Open Provider OAuth2 Consent ↗</a> or paste resulting bearer token above.';
      }
    }catch(e){
      if(fb)fb.textContent='Error: '+e.message;
    }
  };
  if($('btn-comms-toggle-poller'))$('btn-comms-toggle-poller').onclick=async()=>{
    const fb=$('comms-form-feedback');
    try{
      const res=await api.request('/api/steward/comms',{action:'start_poller',interval_sec:900});
      if(fb)fb.textContent='✓ Background IMAP/ICS Auto-Poller active (every 15m · daemon thread).';
      renderWave9Comms(res);
    }catch(e){
      if(fb)fb.textContent='Error: '+e.message;
    }
  };

  document.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();leave();}});
  window.addEventListener('message',event=>{
    if(window.parent===window || event.origin!==location.origin || event.source!==window.parent || !event.data || event.data.type!=='anchor-setup-open')return;
    api.request('/api/provider-setup').then(render).catch(error=>$('setup-message').textContent=error.message);
  });
  renderWave3All();
  const reqSec=new URLSearchParams(location.search).get('section') || (location.hash?location.hash.replace('#',''):'');
  api.request('/api/provider-setup').then(value=>{
    render(value);
    if(reqSec && ['host','providers','chart','comms'].includes(reqSec)){
      section(reqSec);
    }else{
      section(value.host.configured?'providers':'host');
    }
  }).catch(error=>$('setup-message').textContent=error.message);
})();
