const $ = (id) => document.getElementById(id);
const pretty = (v) => JSON.stringify(v, null, 2);
let selectedMissionId = null;
let missionCache = [];
const _fragment = new URLSearchParams(location.hash.startsWith('#') ? location.hash.slice(1) : '');
let accessToken = _fragment.get('access') || localStorage.getItem('sb_access_token') || '';
if (accessToken) { localStorage.setItem('sb_access_token', accessToken); if (location.hash) history.replaceState(null, '', location.pathname + location.search); }

async function api(url, opts={}) {
  const headers = new Headers(opts.headers || {});
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  const r = await fetch(url, {...opts, headers});
  let j = {};
  try { j = await r.json(); } catch { j = {detail: r.statusText}; }
  if (!r.ok) {
    const err = new Error(j.detail || j.error || r.statusText);
    err.code = j.error || 'request_failed'; err.status = r.status; throw err;
  }
  return j;
}
function escapeHtml(value){return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;')}
function fmtDate(value){if(!value)return '—';try{return new Date(value).toLocaleString()}catch{return value}}
function boolLabel(v){return v ? ['READY','ok'] : ['NOT READY','warn']}

function renderInteractiveResponse(result){
  const drafts=(result.draft_responses||[]).map(item=>`<article class="draft"><div class="draft-meta">${escapeHtml(item.agent)} · ${escapeHtml(item.provider)} · ${escapeHtml(item.model)}</div><div class="draft-text">${escapeHtml(item.text)}</div></article>`).join('');
  $('response').classList.remove('hidden');
  $('response').innerHTML=`<div class="response-title"><strong>SuperBrain response</strong></div>${drafts||'<p class="muted">No draft output returned.</p>'}<div class="verification ${result.pipeline_passes?.verifier?'ok':'warn'}"><strong>Nexus gate:</strong> ${escapeHtml(result.nexus_final_value)} · ${escapeHtml(result.verification_note)}</div>`;
}
function renderResearchResponse(result){
  const drafts=(result.draft_responses||[]).map(item=>`<article class="draft"><div class="draft-meta">${escapeHtml(item.agent)} · ${escapeHtml(item.provider)} · ${escapeHtml(item.model)}</div><div class="draft-text">${escapeHtml(item.text)}</div></article>`).join('');
  const sources=(result.research?.sources||[]).map(source=>`<article class="source-card"><div class="source-meta">${escapeHtml(source.stance)} · ${escapeHtml(source.source_family)} · rank ${escapeHtml(source.rank)}</div><div class="source-title">${escapeHtml(source.title)}</div><a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.url)}</a><div class="source-excerpt">${escapeHtml(source.excerpt)}</div></article>`).join('');
  $('response').classList.remove('hidden');
  $('response').innerHTML=`<div class="response-title"><strong>SuperBrain research response</strong></div>${drafts||'<p class="muted">Research completed. No model provider was available for natural-language synthesis.</p>'}<div class="verification ${Object.values(result.pipeline_passes||{}).every(Boolean)?'ok':'warn'}"><strong>Nexus evidence gate:</strong> ${escapeHtml(result.nexus_final_value)} · ${escapeHtml(result.verification_note)}</div><h3 class="source-heading">Research sources</h3>${sources||'<p class="muted">No retrievable sources returned.</p>'}`;
}

function renderDeepResearchResponse(result){
  const deep=result.deep_research||{};
  const drafts=(result.draft_responses||[]).map(item=>`<article class="draft"><div class="draft-meta">${escapeHtml(item.agent)} · ${escapeHtml(item.provider)} · ${escapeHtml(item.model)}</div><div class="draft-text">${escapeHtml(item.text)}</div></article>`).join('');
  const sources=(deep.sources||[]).map(source=>`<article class="source-card"><div class="source-meta">${escapeHtml(source.stance)} · ${escapeHtml(source.source_family)} · rank ${escapeHtml(source.rank)}</div><div class="source-title">${escapeHtml(source.title)}</div><a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.url)}</a><div class="source-excerpt">${escapeHtml(source.excerpt)}</div></article>`).join('');
  const rounds=(deep.rounds||[]).map(round=>{
    const curiosity=round.curiosity_decision||null;
    const questions=(curiosity?.questions||[]).map(q=>`<li><strong>${escapeHtml(q.route)}</strong> · ${escapeHtml(q.question)} <span class="muted">(gain ${escapeHtml(q.expected_information_gain)}, VOI ${escapeHtml(q.value_of_information)}, priority ${escapeHtml(q.priority)}${q.falsification?' · falsification':''})</span></li>`).join('');
    return `<article class="source-card"><div class="source-meta">Round ${escapeHtml(round.round_number)} · ${escapeHtml((round.new_source_ids||[]).length)} new source(s)</div><div class="source-title">${escapeHtml((round.plan?.queries||[]).map(q=>q.purpose).join(' · '))}</div>${curiosity?`<div class="source-excerpt"><strong>Curiosity planner:</strong> expected gain ${escapeHtml(curiosity.total_expected_information_gain)} · top question: ${escapeHtml(curiosity.top_question||'none')}</div>${questions?`<ul>${questions}</ul>`:''}`:''}<div class="source-excerpt">Remaining gaps: ${escapeHtml((round.knowledge_gaps_after||[]).map(g=>g.description).join(' | ')||'none')}</div></article>`;
  }).join('');
  const gaps=(deep.knowledge_gaps||[]).map(g=>`<li>${escapeHtml(g.description)}</li>`).join('');
  const curiosityQuestions=(deep.curiosity_questions||[]).map(q=>`<li><strong>${escapeHtml(q.route)}</strong> · ${escapeHtml(q.question)} <span class="muted">gain ${escapeHtml(q.expected_information_gain)} · cost ${escapeHtml(q.estimated_cost)} · VOI ${escapeHtml(q.value_of_information)}</span></li>`).join('');
  $('response').classList.remove('hidden');
  $('response').innerHTML=`<div class="response-title"><strong>SuperBrain autonomous research</strong></div>${drafts||'<p class="muted">Research completed. No model provider was available for natural-language synthesis.</p>'}<div class="verification ${Object.values(result.pipeline_passes||{}).every(Boolean)?'ok':'warn'}"><strong>Nexus evidence gate:</strong> ${escapeHtml(result.nexus_final_value)} · ${escapeHtml(result.verification_note)}</div><h3 class="source-heading">Research loop</h3><div class="source-excerpt">Stop reason: <strong>${escapeHtml(deep.stop_reason||'unknown')}</strong> · rounds: ${escapeHtml(deep.round_count||0)} · queries: ${escapeHtml(deep.total_queries||0)} · sources: ${escapeHtml((deep.sources||[]).length)}</div>${curiosityQuestions?`<h3 class="source-heading">Curiosity questions</h3><ul>${curiosityQuestions}</ul>`:''}${rounds||'<p class="muted">No research rounds returned.</p>'}${gaps?`<h3 class="source-heading">Remaining evidence gaps</h3><ul>${gaps}</ul>`:''}<h3 class="source-heading">Research sources</h3>${sources||'<p class="muted">No retrievable sources returned.</p>'}`;
}


function renderWorldModel(beliefs){
  const rows=beliefs||[];
  $('world-model-count').textContent=`${rows.length} beliefs`;
  $('world-badge').textContent=rows.length?`${rows.length} tracked`:'empty';
  if(!rows.length){
    $('world-model-list').innerHTML='<div class="empty-state">No persistent beliefs yet. Run an evidence, research or deep-research mission.</div>';
    $('world-summary').textContent='No beliefs tracked yet.';
    return;
  }
  const stateClass=(state)=>String(state||'UNKNOWN').toLowerCase();
  $('world-summary').innerHTML=rows.slice(0,3).map(item=>`<div class="world-mini"><span class="world-state ${stateClass(item.state)}">${escapeHtml(item.state)}</span><strong>${escapeHtml(item.proposition)}</strong><span>${escapeHtml((Number(item.confidence||0)*100).toFixed(0))}% confidence</span></div>`).join('');
  $('world-model-list').innerHTML=rows.map(item=>`<article class="world-item"><div class="world-item-head"><span class="world-state ${stateClass(item.state)}">${escapeHtml(item.state)}</span><strong>${escapeHtml((Number(item.confidence||0)*100).toFixed(1))}%</strong></div><div class="world-proposition">${escapeHtml(item.proposition)}</div><div class="world-metrics"><span>support ${escapeHtml(Number(item.support_strength||0).toFixed(2))}</span><span>challenge ${escapeHtml(Number(item.challenge_strength||0).toFixed(2))}</span><span>${escapeHtml(item.evidence_count)} evidence</span><span>${escapeHtml(item.unique_source_count)} sources</span><span>${escapeHtml(item.unique_family_count)} families</span><span>${escapeHtml(item.revision_count)} revisions</span></div></article>`).join('');
}
function renderChanges(changes){
  const rows=changes||[];
  $('changes-count').textContent=`${rows.length} changes`;
  if(!rows.length){$('changes-list').innerHTML='<div class="empty-state">No material changes detected yet.</div>';return;}
  $('changes-list').innerHTML=rows.map(item=>`<article class="world-item"><div class="world-item-head"><span class="world-state ${escapeHtml(String(item.severity||'LOW').toLowerCase())}">${escapeHtml(item.severity||'LOW')}</span><strong>${escapeHtml(item.event_type||'CHANGE')}</strong></div><div class="world-proposition">${escapeHtml(item.title||'Material change')}</div><div class="source-excerpt">${escapeHtml(item.detail||'')} · ${escapeHtml(item.created_at||'')}</div></article>`).join('');
}

function renderOsintDiagnostics(result){
  const overall=String(result?.overall||'FAIL');
  $('osint-badge').textContent=overall;
  $('osint-badge').className=`mini-badge ${overall==='PASS'?'osint-pass':'osint-fail'}`;
  const providers=(result?.providers||[]).map(item=>`<div class="osint-row"><span>${escapeHtml(item.provider)}</span><strong class="${item.search==='PASS'||item.search==='PASS_NO_RESULTS'||item.status==='PASS'?'ok':'warn'}">${escapeHtml(item.search||item.status||'UNKNOWN')}</strong><small>${escapeHtml(item.retrieval||item.local_proxy||item.error||'')}</small></div>`).join('');
  const onion=result?.onion||{};
  $('osint-result').innerHTML=`<div class="osint-grid">${providers}</div><div class="osint-onion"><span>Onion diagnostic</span><strong class="${onion.status==='PASS'?'ok':onion.status==='POLICY_ONLY'?'muted':'warn'}">${escapeHtml(onion.status||'UNKNOWN')}</strong></div><div class="muted osint-note">${escapeHtml(result?.timestamp||'')} · credential values exposed: ${result?.credential_values_exposed?'YES':'NO'}</div>`;
}

function renderRuntime(system){
  $('metric-missions').textContent=system.mission_count ?? 0;
  $('metric-completed').textContent=system.completed_count ?? 0;
  $('metric-models').textContent=(system.configured_providers||[]).length;
  $('metric-search').textContent=(system.configured_search_providers||[]).length;
  $('metric-models-sub').textContent=(system.configured_providers||[]).join(', ')||'none configured';
  $('metric-search-sub').textContent=(system.configured_search_providers||[]).join(', ')||'none configured';
  const checks=system.runtime_checks||{};
  const rows=[
    ['Python', Boolean(checks.python), checks.python||'unknown'],
    ['Node.js', Boolean(checks.node_available), checks.node_version||'not found'],
    ['Provider bridge', Boolean(checks.provider_bridge_prebuilt), checks.provider_bridge_prebuilt?'prebuilt':'missing'],
    ['Quick answer', Boolean(system.interactive_missions_available), system.interactive_missions_available?'ready':'needs model key'],
    ['Research', Boolean(system.research_missions_available), system.research_missions_available?'ready':'needs search key'],
    ['Deep research', Boolean(system.deep_research_available), system.deep_research_available?'ready':'needs search key'],
    ['Curiosity planner', Boolean(system.curiosity_research_available), system.curiosity_research_available?'ready':'needs search key'],
    ['GitHub OSINT', Boolean(system.github_integration?.enabled), system.github_integration?.authenticated?'authenticated':'public API'],
    ['DuckDuckGo', Boolean(system.duckduckgo_integration?.enabled), system.duckduckgo_integration?.enabled?'enabled':'disabled'],
    ['Egress', Boolean(system.research_routing), system.research_routing?.mode||'unknown'],
    ['Onion research', Boolean(system.research_routing?.onion_research_allowed), system.research_routing?.onion_research_allowed?'allowlist active':'explicit Tor allowlist required'],
    ['Stealth mode', Boolean(system.stealth_mode), system.stealth_mode?'loopback + API auth':'off'],
  ];
  $('runtime-cards').innerHTML=rows.map(([label,ok,detail])=>`<div class="runtime-item"><span>${escapeHtml(label)}</span><strong class="${ok?'ok':'warn'}">${escapeHtml(detail)}</strong></div>`).join('');
  const allReady=system.interactive_missions_available&&system.research_missions_available;
  $('runtime-badge').textContent=allReady?'ready':'setup needed';
  $('setup-summary').textContent=`${system.ui_version||'SuperBrain'} · canonical runtime: ${system.canonical_runtime}`;
  $('setup-detail').textContent=pretty(system);
}
function renderMissions(missions){
  missionCache=missions||[]; $('mission-count-label').textContent=`${missionCache.length} missions`; $('missions').innerHTML='';
  if(!missionCache.length){$('missions').innerHTML='<div class="empty-state">No missions yet. Start one above.</div>';return}
  for(const m of missionCache){
    const row=document.createElement('div'); row.className='mission-row'+(m.run_id===selectedMissionId?' selected':'');
    const fv=String(m.final_value||'—'); row.innerHTML=`<div class="mission-decision ${fv.toLowerCase()}">${escapeHtml(fv)}</div><div class="mission-status">${escapeHtml(m.status)}</div><div class="mission-question">${escapeHtml(m.question)}</div><div class="mission-time">${escapeHtml(fmtDate(m.updated_at||m.created_at))}</div>`;
    row.onclick=()=>loadMission(m.run_id); $('missions').appendChild(row);
  }
}
function renderMissionDetail(detail){
  const run=detail.run||{}, evidence=detail.evidence||[], audit=detail.audit||[], master=detail.master_decisions||[], belief=detail.world_model||null;
  $('detail-empty').classList.add('hidden'); $('detail-dashboard').classList.remove('hidden'); $('selected-status').textContent=run.status||'selected';
  $('detail-final').textContent=run.final_value||'—'; $('detail-final').style.color=run.final_value==='NO'?'#ff9aa0':'#7fe3bf';
  $('detail-evidence-count').textContent=evidence.length; $('detail-audit-count').textContent=audit.length; $('detail-master-count').textContent=master.length;
  $('detail-question').textContent=run.question||'—'; $('detail-run-id').textContent=`Run: ${run.run_id||'—'}`; $('detail-created').textContent=`Created: ${fmtDate(run.created_at)}`;
  $('detail-world-model').classList.toggle('hidden',!belief); $('detail-world-model').innerHTML=belief?`<span class="world-state ${String(belief.state||'UNKNOWN').toLowerCase()}">${escapeHtml(belief.state)}</span><strong>${escapeHtml((Number(belief.confidence||0)*100).toFixed(1))}% confidence</strong><span>${escapeHtml(belief.evidence_count)} accumulated evidence · ${escapeHtml(belief.revision_count)} revisions</span>`:'';
  $('evidence-list').innerHTML=evidence.length?evidence.map(item=>`<article class="evidence-item"><div class="evidence-head"><strong>${escapeHtml(item.source_family||item.source_id||item.id||'Evidence')}</strong><span class="${item.verified?'badge-ok':'badge-warn'}">${item.verified?'VERIFIED':'UNVERIFIED'}</span></div><div class="evidence-claim">${escapeHtml(item.claim||'')}</div><div class="evidence-foot"><span>${escapeHtml(item.stance||'')}</span><span>reliability ${escapeHtml(item.reliability??'—')}</span><span>${escapeHtml(item.provider||'')}</span></div>${item.citation?`<div class="source-excerpt">${escapeHtml(item.citation)}</div>`:''}</article>`).join(''):'<div class="empty-state">No evidence persisted for this run.</div>';
  $('audit-list').innerHTML=audit.length?audit.map(item=>`<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-content"><strong>${escapeHtml(item.stage)}</strong><span>${escapeHtml(item.detail)}</span></div></div>`).join(''):'<div class="empty-state">No audit events.</div>';
  $('master-history').innerHTML=master.length?master.map(item=>`<div class="decision-item"><strong>${escapeHtml(item.action)}</strong><span>${escapeHtml(item.note||'No note')}</span><time>${escapeHtml(fmtDate(item.created_at))}</time></div>`).join(''):'<div class="muted">No Master decision recorded yet.</div>';
  $('detail').textContent=pretty(detail);
  renderMissions(missionCache);
}
async function refresh(){
  try{const h=await api('/health');$('health').textContent=h.status;$('side-health').textContent='Online';$('side-dot').className='dot ok'}catch{$('health').textContent='offline';$('side-health').textContent='Offline';$('side-dot').className='dot bad'}
  try{const system=await api('/api/system/status');renderRuntime(system);const modelText=system.configured_providers?.length?'Models: '+system.configured_providers.join(', '):'No model provider configured';const searchText=system.configured_search_providers?.length?'Search: '+system.configured_search_providers.join(', '):'No web-search provider configured';$('ask-status').textContent=(system.interactive_missions_available&&system.research_missions_available)?`${modelText} · ${searchText} · ready`:`Setup: ${modelText} · ${searchText}`;}catch(e){$('setup-detail').textContent=e.message}
  try{const data=await api('/api/missions');renderMissions(data.missions||[])}catch(e){$('missions').innerHTML=`<div class="empty-state">${escapeHtml(e.message)}</div>`}
  try{const world=await api('/api/world-model?limit=50');renderWorldModel(world.beliefs||[])}catch(e){$('world-model-list').innerHTML=`<div class="empty-state">${escapeHtml(e.message)}</div>`}
  try{const changes=await api('/api/changes?limit=30');renderChanges(changes.changes||[])}catch(e){$('changes-list').innerHTML=`<div class="empty-state">${escapeHtml(e.message)}</div>`}
}
async function loadMission(id){try{selectedMissionId=id;const detail=await api('/api/missions/'+encodeURIComponent(id));renderMissionDetail(detail);$('master-status').textContent='';document.getElementById('mission-detail').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){$('detail-empty').textContent=e.message}}


$('autonomy-cycle').onclick=async()=>{const mission=$('mission').value.trim();$('autonomy-cycle').disabled=true;$('autonomy-cycle').textContent='Running intelligence cycle…';$('autonomy-badge').textContent='running';$('autonomy-result').innerHTML='<div class=\"muted\">Observe → research → Nexus → World Model → assurance…</div>';try{const body=mission?{missions:[mission]}:{};const r=await api('/api/autonomy/cycle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});$('autonomy-badge').textContent=r.status;const steps=r.steps||[];$('autonomy-result').innerHTML=`<div class=\"verification ${r.status==='COMPLETED'?'ok':'warn'}\"><strong>${escapeHtml(r.status)}</strong> · ${steps.length} step(s) · ${escapeHtml((r.next_actions||[]).join(' · ')||'none')}<br>${steps.map(s=>`${escapeHtml(s.belief_state||'UNKNOWN')} · confidence ${escapeHtml(s.belief_confidence??'—')} · assurance ${escapeHtml(s.assurance_status)} ${escapeHtml(s.assurance_score)}`).join('<br>')}</div>`;await refresh()}catch(e){$('autonomy-badge').textContent='BLOCKED';$('autonomy-result').innerHTML=`<div class=\"verification warn\"><strong>Cycle blocked.</strong> ${escapeHtml(e.message)}</div>`}finally{$('autonomy-cycle').disabled=false;$('autonomy-cycle').textContent='Run intelligence cycle'}};
$('osint-diagnostics').onclick=async()=>{
  $('osint-diagnostics').disabled=true; $('osint-diagnostics').textContent='Testing…'; $('osint-result').innerHTML='<div class="muted">Running GitHub, DuckDuckGo, guarded retrieval and local Tor diagnostics…</div>';
  try{const r=await api('/api/osint/diagnostics',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});renderOsintDiagnostics(r);}
  catch(e){$('osint-badge').textContent='FAIL';$('osint-badge').className='mini-badge osint-fail';$('osint-result').innerHTML=`<div class="verification warn"><strong>OSINT diagnostic failed.</strong> ${escapeHtml(e.message)}</div>`;}
  finally{$('osint-diagnostics').disabled=false;$('osint-diagnostics').textContent='Run live OSINT test';}
};
$('autonomous-research').onclick=async()=>{const mission=$('mission').value.trim();if(!mission){$('ask-status').textContent='Type a mission first.';$('mission').focus();return}$('autonomous-research').disabled=true;$('autonomous-research').textContent='Planning & researching…';$('ask-status').textContent='Curiosity planner is ranking knowledge gaps, falsification questions and expected information gain…';$('response').classList.add('hidden');try{const r=await api('/api/missions/autonomous-research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mission,max_rounds:4,max_total_sources:16,max_results_per_query:3})});renderDeepResearchResponse(r);selectedMissionId=r.run_id;await refresh();await loadMission(r.run_id);$('ask-status').textContent=`Autonomous research completed: ${r.deep_research?.stop_reason||'finished'}.`}catch(e){$('ask-status').textContent=e.message;$('response').classList.remove('hidden');$('response').innerHTML=e.code==='research_unavailable'?'<div class="verification warn"><strong>Autonomous research setup required.</strong> Add TAVILY_API_KEY or BRAVE_SEARCH_API_KEY to .env and restart.</div>':`<div class="verification warn"><strong>Autonomous research failed.</strong> ${escapeHtml(e.message)}</div>`}finally{$('autonomous-research').disabled=false;$('autonomous-research').textContent='Autonomous research'}};
$('deep-research').onclick=async()=>{const mission=$('mission').value.trim();if(!mission){$('ask-status').textContent='Type a mission first.';$('mission').focus();return}$('deep-research').disabled=true;$('deep-research').textContent='Deep researching…';$('ask-status').textContent='Running iterative research, counter-evidence search and information-gap checks…';$('response').classList.add('hidden');try{const r=await api('/api/missions/deep-research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mission,max_rounds:3,max_total_sources:12,max_results_per_query:3})});renderDeepResearchResponse(r);selectedMissionId=r.run_id;await refresh();await loadMission(r.run_id);$('ask-status').textContent=`Deep research completed: ${r.deep_research?.stop_reason||'finished'}.`}catch(e){$('ask-status').textContent=e.message;$('response').classList.remove('hidden');$('response').innerHTML=e.code==='research_unavailable'?'<div class="verification warn"><strong>Deep research setup required.</strong> Add TAVILY_API_KEY or BRAVE_SEARCH_API_KEY to .env and restart.</div>':`<div class="verification warn"><strong>Deep research failed.</strong> ${escapeHtml(e.message)}</div>`}finally{$('deep-research').disabled=false;$('deep-research').textContent='Deep research'}};
$('research').onclick=async()=>{const mission=$('mission').value.trim();if(!mission){$('ask-status').textContent='Type a mission first.';$('mission').focus();return}$('research').disabled=true;$('research').textContent='Researching…';$('ask-status').textContent='Searching, retrieving sources and running Nexus evidence gates…';$('response').classList.add('hidden');try{const r=await api('/api/missions/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mission,max_results_per_query:3,max_sources:6})});renderResearchResponse(r);selectedMissionId=r.run_id;await refresh();await loadMission(r.run_id);$('ask-status').textContent='Research mission completed.'}catch(e){$('ask-status').textContent=e.message;$('response').classList.remove('hidden');$('response').innerHTML=e.code==='research_unavailable'?'<div class="verification warn"><strong>Research setup required.</strong> Add TAVILY_API_KEY or BRAVE_SEARCH_API_KEY to .env and restart.</div>':`<div class="verification warn"><strong>Research failed.</strong> ${escapeHtml(e.message)}</div>`}finally{$('research').disabled=false;$('research').textContent='Research & answer'}};
$('ask').onclick=async()=>{const mission=$('mission').value.trim();if(!mission){$('ask-status').textContent='Type a mission first.';$('mission').focus();return}$('ask').disabled=true;$('ask').textContent='Thinking…';$('ask-status').textContent='Running provider specialists and Nexus gates…';$('response').classList.add('hidden');try{const r=await api('/api/missions/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mission})});renderInteractiveResponse(r);selectedMissionId=r.run_id;await refresh();await loadMission(r.run_id);$('ask-status').textContent='Mission completed.'}catch(e){$('ask-status').textContent=e.message;$('response').classList.remove('hidden');$('response').innerHTML=e.code==='provider_unavailable'?'<div class="verification warn"><strong>Provider setup required.</strong> Add OPENAI_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY to .env and restart.</div>':`<div class="verification warn"><strong>Mission failed.</strong> ${escapeHtml(e.message)}</div>`}finally{$('ask').disabled=false;$('ask').textContent='Quick answer'}};
$('demo').onclick=async()=>{$('demo').disabled=true;$('demo').textContent='Running…';try{const r=await api('/api/missions/demo',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});selectedMissionId=r.run_id;await refresh();await loadMission(r.run_id)}catch(e){$('ask-status').textContent=e.message}finally{$('demo').disabled=false;$('demo').textContent='Run deterministic demo'}};
$('save-master').onclick=async()=>{if(!selectedMissionId){$('master-status').textContent='Select a mission first.';return}$('save-master').disabled=true;try{await api('/api/missions/'+encodeURIComponent(selectedMissionId)+'/master-decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:$('master-action').value,note:$('master-note').value})});$('master-status').textContent='Decision recorded.';$('master-note').value='';await loadMission(selectedMissionId)}catch(e){$('master-status').textContent=e.message}finally{$('save-master').disabled=false}};
$('refresh').onclick=refresh;
document.querySelectorAll('.nav-item').forEach(btn=>btn.onclick=()=>{document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));btn.classList.add('active');const target=btn.dataset.target;if(target==='mission-lab')document.querySelector('.ask-panel')?.scrollIntoView({behavior:'smooth'});else document.getElementById(target)?.scrollIntoView({behavior:'smooth'})});
refresh();
