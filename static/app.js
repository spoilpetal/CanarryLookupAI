const $=s=>document.querySelector(s);
let messages=[],chats=[],projects=[],busy=false,modelNames=[],chatId=null,attachments=[],activeProject=null,providerType='ollama',activeRequest=null,uiPrefs={enter_to_send:true,compact_mode:false,default_agent:true,auto_scroll:true};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function markdown(s){let x=esc(s);x=x.replace(/```([\w+-]*)\n([\s\S]*?)```/g,(_,l,c)=>`<pre><code>${c}</code></pre>`);x=x.replace(/`([^`]+)`/g,'<code>$1</code>');x=x.replace(/\*\*(.*?)\*\*/g,'<b>$1</b>').replace(/\*(.*?)\*/g,'<i>$1</i>');return x.split(/\n\n+/).map(p=>p.startsWith('<pre>')?p:`<p>${p.replace(/\n/g,'<br>')}</p>`).join('')}
function scrollLatest(){const a=$('#chatArea');a.scrollTo({top:a.scrollHeight,behavior:'smooth'})}
function followLatest(){if(uiPrefs.auto_scroll){const a=$('#chatArea');a.scrollTop=a.scrollHeight}updateScrollButton()}
function updateScrollButton(){const a=$('#chatArea');$('#scrollDown').classList.toggle('visible',a.scrollHeight-a.scrollTop-a.clientHeight>180)}
function closeSettings(){ $('#modal').classList.remove('open'); }
function setPanel(which,hidden){document.querySelector('.app').classList.toggle(which+'-collapsed',hidden);localStorage.setItem('canarry-'+which+'-collapsed',hidden?'1':'0');$('#show'+(which==='left'?'Left':'Right')).classList.toggle('visible',hidden);requestAnimationFrame(updateScrollButton)}
async function copyText(text,button){try{await navigator.clipboard.writeText(String(text??''));if(button){const old=button.textContent;button.textContent='✓ Copied';setTimeout(()=>button.textContent=old,1200)}}catch(e){const area=document.createElement('textarea');area.value=String(text??'');area.style.position='fixed';area.style.opacity='0';document.body.appendChild(area);area.select();const ok=document.execCommand('copy');area.remove();if(button){const old=button.textContent;button.textContent=ok?'✓ Copied':'Copy failed';setTimeout(()=>button.textContent=old,1200)}}}
function decorateBubble(bubble){bubble.querySelectorAll('pre').forEach(pre=>{if(pre.querySelector('.code-copy'))return;const b=document.createElement('button');b.className='code-copy copy-btn';b.type='button';b.textContent='⧉ Copy code';b.title='Copy code block';b.onclick=()=>copyText(pre.querySelector('code')?.innerText||pre.innerText,b);pre.appendChild(b)})}
function addMessage(role,content){const el=document.createElement('div');el.className='message '+role+(role==='assistant'&&busy?' thinking':'');el.id='message-'+messages.length;const avatar=document.createElement('div');avatar.className='avatar';avatar.textContent=role==='user'?'●':'✦';const body=document.createElement('div');body.className='message-body';const bubble=document.createElement('div');bubble.className='bubble';bubble.innerHTML=markdown(content);decorateBubble(bubble);const actions=document.createElement('div');actions.className='message-actions';const copy=document.createElement('button');copy.className='copy-btn';copy.type='button';copy.textContent='⧉ Copy response';copy.title='Copy this complete response';copy.onclick=()=>{const clean=bubble.cloneNode(true);clean.querySelectorAll('button').forEach(x=>x.remove());copyText(clean.innerText,copy)};actions.appendChild(copy);if(role==='assistant'){const retry=document.createElement('button');retry.className='copy-btn';retry.type='button';retry.textContent='↻ Retry';retry.title='Retry this response using the previous prompt';retry.onclick=retryLastChatPrompt;actions.appendChild(retry);const reuse=document.createElement('button');reuse.className='copy-btn';reuse.type='button';reuse.textContent='↩ Reuse prompt';reuse.title='Put the previous prompt back into the composer';reuse.onclick=()=>reuseLastChatPrompt();actions.appendChild(reuse)}body.append(bubble,actions);el.append(avatar,body);$('#messages').append(el);followLatest();return bubble}
function reuseLastChatPrompt(){const last=[...messages].reverse().find(m=>m.role==='user');if(!last)return;$('#prompt').value=last.content||'';$('#prompt').focus();$('#prompt').style.height='auto';$('#prompt').style.height=Math.min($('#prompt').scrollHeight,190)+'px'}
function retryLastChatPrompt(){reuseLastChatPrompt();if($('#prompt').value.trim())send()}
function addTool(name,args,result){const el=document.createElement('details');el.className='tool-event';const summary=document.createElement('summary');summary.textContent='⚙ '+name+' · completed';const pre=document.createElement('pre');const raw=JSON.stringify({arguments:args,result},null,2);pre.textContent=raw;const copy=document.createElement('button');copy.className='copy-btn code-copy';copy.type='button';copy.textContent='▢ Copy';copy.onclick=()=>copyText(raw,copy);pre.appendChild(copy);el.append(summary,pre);$('#messages').append(el)}
function updateStats(){$('#messageCount')&&($('#messageCount').textContent=messages.length);$('#agentModeStat')&&($('#agentModeStat').textContent=$('#agentToggle').checked?'ON':'OFF')}
function renderOutline(){let users=messages.map((m,i)=>({...m,index:i})).filter(m=>m.role==='user');$('#outline').innerHTML=users.length?users.map((m,n)=>`<button class="outline-item ${n===users.length-1?'latest':''}" data-jump="${m.index}"><span class="outline-number">${String(n+1).padStart(2,'0')}</span><span class="outline-text">${esc((m.content||'').replace(/\s+/g,' ').slice(0,100)||'Attachment')}</span></button>`).join(''):'<div class="outline-empty">Your instructions will appear here</div>';document.querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>{const el=$('#message-'+b.dataset.jump);if(el){el.scrollIntoView({behavior:'smooth',block:'center'});document.querySelectorAll('.outline-item').forEach(x=>x.classList.remove('selected'));b.classList.add('selected')}})}
function renderHistory(){ const visible=chats.filter(c=>!activeProject||c.project_id===activeProject).slice(0,80);$('#history').innerHTML=visible.map(c=>`<div class="history-row"><button data-chat="${esc(c.id)}" class="${c.id===chatId?'active':''}">${c.pinned?'📌 ':''}${esc(c.title)}</button><button class="history-action" data-chat-pin="${esc(c.id)}" title="${c.pinned?'Unpin':'Pin'} conversation">${c.pinned?'◆':'◇'}</button><button class="history-action" data-chat-export="${esc(c.id)}" title="Export conversation as Markdown">↓</button><button class="history-action" data-chat-rename="${esc(c.id)}" title="Rename">✎</button><button class="history-action" data-chat-delete="${esc(c.id)}" title="Delete">×</button></div>`).join('')||'<div class="empty-side">No conversations here yet</div>';document.querySelectorAll('[data-chat]').forEach(b=>b.onclick=()=>openChat(b.dataset.chat));document.querySelectorAll('[data-chat-pin]').forEach(b=>b.onclick=async()=>{const c=chats.find(x=>x.id===b.dataset.chatPin);await fetch('/api/chats/'+b.dataset.chatPin+'/pin',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({pinned:!c?.pinned})});refreshChats()});document.querySelectorAll('[data-chat-export]').forEach(b=>b.onclick=()=>exportChat(b.dataset.chatExport));document.querySelectorAll('[data-chat-rename]').forEach(b=>b.onclick=async()=>{let c=chats.find(x=>x.id===b.dataset.chatRename),title=prompt('Rename conversation',c?.title||'');if(title?.trim()){await fetch('/api/chats/'+b.dataset.chatRename,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:title.trim()})});refreshChats()}});document.querySelectorAll('[data-chat-delete]').forEach(b=>b.onclick=async()=>{if(!confirm('Delete this conversation?'))return;await fetch('/api/chats/'+b.dataset.chatDelete,{method:'DELETE'});if(chatId===b.dataset.chatDelete)await newChat();refreshChats()})}

async function exportChat(id){
  try{
    const response=await fetch('/api/chats/'+encodeURIComponent(id));
    if(!response.ok)throw new Error('Could not load conversation');
    const chat=await response.json();
    const textOf=value=>{
      if(typeof value==='string')return value;
      if(Array.isArray(value))return value.map(part=>typeof part==='string'?part:(part?.text||part?.content||'')).filter(Boolean).join('\n');
      return value==null?'':JSON.stringify(value,null,2);
    };
    const lines=[`# ${chat.title||'Untitled conversation'}`,'',`- Model: ${chat.model||'Not recorded'}`,`- Exported: ${new Date().toISOString()}`,''];
    for(const message of (chat.messages||[])){
      const role=(message.role||'assistant').toUpperCase();
      lines.push(`## ${role}`,'',textOf(message.content||message.text||''),'');
    }
    const blob=new Blob([lines.join('\n')],{type:'text/markdown;charset=utf-8'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    const safe=(chat.title||'conversation').normalize('NFKD').replace(/[^a-z0-9-_]+/gi,'-').replace(/^-+|-+$/g,'').slice(0,60)||'conversation';
    a.href=url;a.download=`${safe}.md`;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  }catch(error){alert(error.message||'Conversation export failed');}
}

async function checkModelCapabilities(model){if(!model)return;const base=`${modelNames.length} model${modelNames.length===1?'':'s'} · ${providerType==='ollama'?'Ollama':'API provider'}`;try{let r=await fetch('/api/model-capabilities/'+encodeURIComponent(model));let d=await r.json();$('#modelMeta').textContent=base+(providerType==='ollama'&&d.known?(d.vision?' · Vision supported':' · No vision capability reported'):(providerType!=='ollama'?' · Model features depend on provider':' · Capabilities unknown'));}catch(e){$('#modelMeta').textContent=base}}
async function refreshChats(){let r=await fetch('/api/chats');chats=await r.json();renderHistory()}
async function loadProjects(){let r=await fetch('/api/projects');projects=await r.json();$('#projectList').innerHTML=`<button class="project-item ${!activeProject?'active':''}" data-project="">◫ <span>All conversations</span></button>`+projects.map(p=>`<button class="project-item ${activeProject===p.id?'active':''}" data-project="${p.id}">▰ <span>${esc(p.name)}</span></button>`).join('');document.querySelectorAll('[data-project]').forEach(b=>b.onclick=async()=>{activeProject=b.dataset.project||null;if(chatId){await fetch('/api/chats/'+chatId+'/project',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:activeProject})});await refreshChats()}renderHistory();loadProjects()});if($('#conversationProjectSelect'))$('#conversationProjectSelect').innerHTML='<option value="">No project</option>'+projects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');if($('#conversationProjectSelect'))$('#conversationProjectSelect').value=activeProject||'';$('#settingsProjects').innerHTML=projects.map(p=>`<div class="project-line"><span>▰ ${esc(p.name)}</span><small>${esc(p.path)}</small></div>`).join('')||'<p class="muted">No project folders yet.</p>'}
async function createProject(){let name=$('#projectName').value.trim()||prompt('Project folder name');if(!name)return;let r=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});if(!r.ok){alert('Could not create project: '+await r.text());return}$('#projectName').value='';const project=await r.json();activeProject=project.id;await loadProjects();if(chatId)await fetch('/api/chats/'+chatId+'/project',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:activeProject})});await refreshChats();renderHistory()}
async function newChat(){messages=[];attachments=[];chatId=null;$('#messages').innerHTML='';$('#welcome').style.display='block';renderAttachments();renderOutline();updateStats();await refreshChats()}
async function openChat(id){let r=await fetch('/api/chats/'+id);if(!r.ok)return;let c=await r.json();chatId=id;messages=c.messages||[];activeProject=c.project_id||null;$('#messages').innerHTML='';$('#welcome').style.display=messages.length?'none':'block';messages.forEach((m,i)=>{const marker=String(m.content||'').match(/\n\n\[Image: (https?:\/\/[^\s]+|\/api\/generated\/[a-f0-9]{32})\]$/);const bubble=addMessage(m.role,marker?String(m.content).replace(marker[0],''):m.content||'');if(marker&&m.role==='assistant')bubble.innerHTML+=`<img class="generated-image" src="${esc(marker[1])}" alt="Generated image">`;});attachments=[];renderAttachments();renderOutline();updateStats();renderHistory();loadProjects();scrollLatest()}
async function ensureChat(){if(chatId)return chatId;let r=await fetch('/api/chats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:$('#modelSelect')?.value||'',project_id:activeProject})});let d=await r.json();chatId=d.id;return chatId}
async function persist(){if(!chatId)return;await fetch('/api/chats/'+chatId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages,model:$('#modelSelect')?.value||'',project_id:activeProject})});await refreshChats();renderOutline()}
async function loadModels(){try{let r=await fetch('/api/models');if(!r.ok)throw Error((await r.json()).detail||await r.text());let d=await r.json();modelNames=(d.models||[]).map(m=>m.name).filter(Boolean);let previous=$('#modelSelect')?.value;$('#modelSelect').innerHTML=modelNames.length?modelNames.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join(''):'<option value="">No models</option>';if(modelNames.includes(previous))$('#modelSelect').value=previous;$('#modelMeta').textContent=`${modelNames.length} model${modelNames.length===1?'':'s'} · ${providerType==='ollama'?'Ollama':'API provider'}`;if(modelNames.length)checkModelCapabilities($('#modelSelect').value);$('#statusDot').classList.add('online');$('#statusText').textContent='Provider connected';$('#providerStatus').textContent=({ollama:'Ollama local API','openai-compatible':'OpenAI-compatible API',anthropic:'Anthropic Messages API',gemini:'Google Gemini API'})[providerType]||'AI provider';$('#providerPill').textContent=providerType==='ollama'?'LOCAL PROVIDER':providerType.toUpperCase()+' API';$('#providerPill').classList.add('online');$('#imageBtn').disabled=!['openai-compatible','gemini'].includes(providerType)}catch(e){$('#modelSelect').innerHTML='<option value="">Provider unavailable</option>';$('#modelMeta').textContent=String(e.message).slice(0,160);$('#statusDot').classList.remove('online');$('#statusText').textContent='Provider unavailable';$('#providerStatus').textContent='Check endpoint / model server';$('#providerPill').textContent='DISCONNECTED';$('#providerPill').classList.remove('online')}}
function renderAttachments(){$('#attachmentList').innerHTML=attachments.map(a=>`<span class="attachment-chip">${a.is_image?'▧':'▤'} ${esc(a.name)} <small>${(a.size/1048576).toFixed(1)} MB</small><button data-remove="${a.id}" title="Remove">×</button></span>`).join('');document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=async()=>{await fetch('/api/uploads/'+b.dataset.remove,{method:'DELETE'});attachments=attachments.filter(a=>a.id!==b.dataset.remove);renderAttachments()})}
async function uploadFiles(files){if(!files.length)return;if(files.length+attachments.length>20){alert('You can attach up to 20 files per turn.');return}await ensureChat();for(const file of files){if(file.size>50*1024*1024){alert(`${file.name} exceeds the 50 MB per-file limit.`);continue}const fd=new FormData();fd.append('file',file);fd.append('chat_id',chatId);$('#uploadHint').textContent='Uploading '+file.name+'…';const r=await fetch('/api/uploads',{method:'POST',body:fd});if(!r.ok){alert('Upload failed: '+await r.text());continue}const uploaded=await r.json();attachments.push(uploaded);if(uploaded.archive&&!uploaded.archive.extracted){alert(`The archive was uploaded but could not be extracted.\n\n${uploaded.archive.error||'Unknown extraction error'}\n\nInstall the required archive helper/dependency, then upload it again.`)}else if(uploaded.archive?.extracted){$('#uploadHint').textContent=`${file.name}: extracted ${uploaded.archive.files} files`}}if(!$('#uploadHint').textContent.includes('extracted'))$('#uploadHint').textContent='50 MB / file · up to 20 files';renderAttachments();$('#fileInput').value=''}
async function consumeStream(response,bubble){let reader=response.body.getReader(),decoder=new TextDecoder(),buf='',assistant='';while(true){let {value,done}=await reader.read();if(done)break;buf+=decoder.decode(value,{stream:true});let parts=buf.split('\n\n');buf=parts.pop();for(let part of parts){let line=part.split('\n').find(l=>l.startsWith('data: '));if(!line)continue;let ev=JSON.parse(line.slice(6));if(ev.type==='clear_response'){assistant='';bubble.innerHTML='';bubble.closest('.message')?.classList.remove('thinking')}else if(ev.type==='token'){bubble.closest('.message')?.classList.remove('thinking');assistant+=ev.text;bubble.innerHTML=markdown(assistant);decorateBubble(bubble);followLatest()}else if(ev.type==='tool')addTool(ev.name,ev.arguments,ev.result);else if(ev.type==='error')throw Error(ev.message||ev.error||JSON.stringify(ev)||'The provider returned an unspecified error.');else if(ev.type==='notice')addTool('notice',{},ev.message)}}return assistant}

let voiceRecognition=null,voiceAutoSend=false,voiceOutputEnabled=localStorage.getItem('canarry-voice-output')==='1';
function updateVoiceControls(){
  const out=$('#voiceOutput'),mic=$('#voiceMic');
  if(out){out.textContent=voiceOutputEnabled?'🔊 Voice reply: On':'🔈 Voice reply: Off';out.setAttribute('aria-pressed',voiceOutputEnabled?'true':'false');out.classList.toggle('voice-active',voiceOutputEnabled)}
  if(mic){mic.classList.toggle('voice-active',!!voiceRecognition);mic.title=voiceRecognition?'Stop voice input':'Start voice input'}
}
function speakAssistant(text){
  if(!voiceOutputEnabled||!('speechSynthesis' in window)||!text)return;
  try{speechSynthesis.cancel();const clean=String(text).replace(/```[\s\S]*?```/g,' Code block omitted. ').replace(/<[^>]+>/g,' ').replace(/https?:\/\/\S+/g,' link ').replace(/[*_#`]/g,' ').slice(0,12000);const utterance=new SpeechSynthesisUtterance(clean);utterance.rate=1; speechSynthesis.speak(utterance)}catch(e){console.warn('Voice output unavailable',e)}
}
function startVoiceInput(){
  const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SpeechRecognition){alert('Voice input is not supported by this browser. Try a recent Chromium-based browser.');return}
  if(voiceRecognition){voiceAutoSend=false;voiceRecognition.stop();voiceRecognition=null;updateVoiceControls();return}
  const rec=new SpeechRecognition();rec.lang=navigator.language||'en-US';rec.interimResults=true;rec.continuous=false;
  voiceRecognition=rec;voiceAutoSend=true;let finalText='';
  rec.onresult=e=>{let interim='';for(let i=e.resultIndex;i<e.results.length;i++){const phrase=e.results[i][0].transcript;if(e.results[i].isFinal)finalText+=phrase+' ';else interim+=phrase}$('#prompt').value=(finalText+interim).trim();$('#prompt').dispatchEvent(new Event('input'))};
  rec.onerror=e=>{voiceAutoSend=false;voiceRecognition=null;updateVoiceControls();if(e.error!=='no-speech'&&e.error!=='aborted')alert('Voice input error: '+e.error)};
  rec.onend=()=>{const shouldSend=voiceAutoSend&&finalText.trim().length>0;voiceAutoSend=false;voiceRecognition=null;updateVoiceControls();if(shouldSend&&!busy)send()};
  updateVoiceControls();try{rec.start()}catch(e){voiceRecognition=null;voiceAutoSend=false;updateVoiceControls();alert('Could not start voice input: '+e.message)}
}
async function send(){if(busy){activeRequest?.abort();return}let text=$('#prompt').value.trim();if((!text&&!attachments.length)||busy)return;let model=$('#modelSelect').value;if(!model){alert('No model is available. Check your provider settings.');return}await ensureChat();busy=true;activeRequest=new AbortController();$('#sendBtn').textContent='■';$('#sendBtn').title='Stop generation';$('#welcome').style.display='none';$('#prompt').value='';$('#prompt').style.height='auto';let shown=text||'Please inspect the attached files.';if(attachments.length)shown+='\n\n📎 '+attachments.map(a=>a.name).join(', ');messages.push({role:'user',content:shown,attachment_ids:attachments.map(a=>a.id)});addMessage('user',shown);renderOutline();let bubble=addMessage('assistant',''),assistant='';$('#agentStatus')&&($('#agentStatus').textContent='Working');
 try{let r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages,model,agent:$('#agentToggle').checked,chat_id:chatId,attachment_ids:attachments.map(a=>a.id),memory_enabled:$('#memoryToggle').checked}),signal:activeRequest.signal});if(!r.ok){let body=await r.text();try{const parsed=JSON.parse(body);body=parsed.detail||parsed.error||parsed.message||body}catch{}throw Error(body||`Request failed (${r.status}). The server did not return an error description.`)}assistant=await consumeStream(r,bubble)}catch(e){if(e.name==='AbortError'){assistant+=(assistant?'\n\n':'')+'*Generation stopped.*'}else{assistant+=(assistant?'\n\n':'')+'**Error:** '+(e.message||'Unknown provider error. Check the server log and provider response.')}bubble.closest('.message')?.classList.remove('thinking');bubble.innerHTML=markdown(assistant);decorateBubble(bubble)}
 messages.push({role:'assistant',content:assistant});speakAssistant(assistant);attachments=[];renderAttachments();await persist();$('#agentStatus')&&($('#agentStatus').textContent='Ready');busy=false;activeRequest=null;$('#sendBtn').textContent='↑';$('#sendBtn').title='Send';updateStats();renderOutline();}
async function generateImage(){let prompt=$('#prompt').value.trim();if(!prompt||busy)return;if(!['openai-compatible','gemini'].includes(providerType)){alert('Image generation is not available through this provider adapter.');return}busy=true;$('#imageBtn').disabled=true;try{await ensureChat();const r=await fetch('/api/images/generations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,model:$('#imageModel').value.trim()||'dall-e-3'})});let d=await r.json();if(!r.ok)throw Error(d.detail||JSON.stringify(d));let url=d.url||d.data?.[0]?.url, dataUrl=d.data_url;if(url||dataUrl){const content=`Image generated for: ${prompt}\n\n[Image: ${url||dataUrl}]`;messages.push({role:'assistant',content});const bubble=addMessage('assistant',`Image generated for: ${prompt}`);if(url)bubble.innerHTML+=`<p><a href="${esc(url)}" target="_blank" rel="noopener">Open generated image</a></p><img class="generated-image" src="${esc(url)}" alt="Generated image">`;else bubble.innerHTML+=`<img class="generated-image" src="${esc(dataUrl)}" alt="Generated image">`;await persist();renderOutline();}else addMessage('assistant','Image provider returned no displayable image.');$('#prompt').value=''}catch(e){alert('Image generation failed: '+e.message)}finally{busy=false;$('#imageBtn').disabled=!['openai-compatible','gemini'].includes(providerType)}}

async function exportAllChats(){
  try{
    const response=await fetch('/api/chats/export');
    if(!response.ok)throw new Error(await response.text()||'Could not export conversations');
    const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='CanarryLookupAI-chats.zip';document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){alert(error.message||'Conversation export failed');}
}
async function loadNetworkStatus(){
  try{
    const r=await fetch('/api/network/status');if(!r.ok)throw Error(await r.text());const d=await r.json();
    const list=$('#lanAddressList');list.innerHTML='';
    if(d.lan_urls?.length){d.lan_urls.forEach(url=>{const a=document.createElement('a');a.href=url;a.textContent=url;a.target='_blank';a.rel='noopener';list.appendChild(a)})}
    else list.textContent='No LAN address found. Check that this computer is connected to your network.';
    $('#networkAuthEnabled').checked=d.auth_enabled;$('#networkAuthState').textContent=d.auth_enabled?'Sign-in required':'No password';
    $('#networkAuthState').classList.toggle('network-secure',d.auth_enabled);
    if(d.username)$('#networkUsername').value=d.username;
    const t=d.tunnel||{};
    if(t.running||t.url){$('#tunnelStatus').textContent=t.url?'Connected using '+(t.provider||'tunnel'):'Establishing '+(t.provider||'tunnel')+' connection…';$('#stopTunnel').hidden=false;$('#startTunnel').disabled=true}
    else{$('#tunnelStatus').textContent=t.error||'No public connection established.';$('#stopTunnel').hidden=true;$('#startTunnel').disabled=false}
    $('#tunnelAddress').innerHTML='';
    if(t.url){const a=document.createElement('a');a.href=t.url;a.textContent=t.url;a.target='_blank';a.rel='noopener';$('#tunnelAddress').appendChild(a)}
    const provider=$('#tunnelProvider').value;$('#cloudflareHostnameLabel').hidden=provider!=='cloudflare';$('#tunnelCredential').disabled=provider==='tailscale';$('#tunnelCredential').placeholder=provider==='tailscale'?'Tailscale uses the host CLI sign-in':'Enter provider token (blank keeps saved token)';$('#saveTunnelCredential').disabled=provider==='tailscale';$('#clearTunnelCredential').disabled=provider==='tailscale';
    if(d.providers && d.providers[provider]===false)$('#tunnelStatus').textContent='Provider CLI not detected. Install '+provider+' first.';
    if(t.running&&!t.url)setTimeout(loadNetworkStatus,1800);
  }catch(e){$('#lanAddressList').textContent='Could not load network details: '+e.message}
}
async function saveNetworkAuth(){
  const enabled=$('#networkAuthEnabled').checked,username=$('#networkUsername').value.trim(),password=$('#networkPassword').value;
  $('#networkAuthResult').textContent='Saving…';
  try{
    const r=await fetch('/api/network/auth',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled,username,password})});
    if(!r.ok)throw Error(await r.text());
    $('#networkPassword').value='';$('#networkAuthResult').textContent='Saved. '+(enabled?'Reloading so the browser can request your new sign-in.':'Password-free LAN access is enabled.');
    if(enabled){setTimeout(()=>window.location.reload(),700)}else{await loadNetworkStatus()}
  }catch(e){$('#networkAuthResult').textContent='Could not save: '+e.message}
}
async function loadPairedDevices(){
  const r=await fetch('/api/device/list');if(!r.ok)return;const rows=await r.json();
  $('#pairedDevicesList').innerHTML=rows.map(d=>`<div class="project-line"><span><b>${esc(d.name)}</b> · ${d.is_owner?'Owner':(d.paired?'Paired':'Awaiting pairing')} · ${d.harness_mode?'Harness':'Normal'}</span>${d.is_owner?'':`<button data-revoke-device="${d.id}">Revoke</button>`}</div>`).join('');
  document.querySelectorAll('[data-revoke-device]').forEach(b=>b.onclick=async()=>{if(!confirm('Revoke this device? Its browser will lose access.'))return;const x=await fetch('/api/device/'+b.dataset.revokeDevice,{method:'DELETE'});if(!x.ok)alert(await x.text());loadPairedDevices()});
}
async function saveHarnessMode(){const enabled=$('#harnessModeToggle').checked;if(enabled&&!confirm('Harness mode grants this device identity access to its private workspace and restricted shell tools on the CanarryLookup host. It does not control the phone/browser computer. Enable it only on a device you trust. Continue?')){$('#harnessModeToggle').checked=false;return}const r=await fetch('/api/device/mode',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({harness_mode:enabled})});if(!r.ok){$('#harnessModeResult').textContent=await r.text();return}$('#harnessModeResult').textContent=enabled?'Harness mode enabled on this device.':'Normal mode enabled.'}
async function createPairCode(){const r=await fetch('/api/device/pair-code',{method:'POST'});if(!r.ok){$('#pairCodeOutput').textContent=await r.text();return}const d=await r.json();$('#pairCodeOutput').textContent='One-time code (10 minutes): '+d.code+' — enter this on the new device.'}
async function saveTunnelCredential(){const provider=$('#tunnelProvider').value,token=$('#tunnelCredential').value,hostname=$('#cloudflareHostname').value.trim();const r=await fetch('/api/network/tunnel/credentials',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider,token,hostname})});if(!r.ok){$('#tunnelCredentialResult').textContent=await r.text();return}$('#tunnelCredential').value='';$('#tunnelCredentialResult').textContent='Saved on the owner host. The secret is not displayed again.'}
async function clearTunnelCredential(){const provider=$('#tunnelProvider').value;if(provider==='tailscale')return;if(!confirm('Clear the saved '+provider+' token from the owner device?'))return;const r=await fetch('/api/network/tunnel/credentials',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider,clear:true})});if(!r.ok){$('#tunnelCredentialResult').textContent=await r.text();return}$('#tunnelCredentialResult').textContent='Saved token cleared.'}
async function ensureDevicePaired(){
  try{const r=await fetch('/api/device/status');if(!r.ok)return false;const d=await r.json();if(d.paired)return true;const code=prompt('This browser is not paired with the CanarryLookup host. Enter the one-time pairing code generated on the owner device:');if(!code)return false;const name=prompt('Give this device a name (for example, Phone or Laptop):','My device')||'Paired device';const pair=await fetch('/api/device/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,name})});if(!pair.ok){alert('Pairing failed: '+await pair.text());return false}return true}catch(e){alert('Could not verify device pairing: '+e.message);return false}
}

async function startPublicTunnel(){
  const provider=$('#tunnelProvider').value,b=$('#startTunnel');b.disabled=true;$('#tunnelStatus').textContent='Establishing secure connection…';
  try{
    const r=await fetch('/api/network/tunnel/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider})});
    if(!r.ok)throw Error(await r.text());await loadNetworkStatus();
  }catch(e){$('#tunnelStatus').textContent=e.message;b.disabled=false}
}
async function stopPublicTunnel(){
  $('#stopTunnel').disabled=true;
  try{const r=await fetch('/api/network/tunnel/stop',{method:'POST'});if(!r.ok)throw Error(await r.text());await loadNetworkStatus()}
  catch(e){$('#tunnelStatus').textContent=e.message}
  finally{$('#stopTunnel').disabled=false}
}

async function loadSettings(){let r=await fetch('/api/settings'),s=await r.json();$('#memoryToggle').checked=s.memory_enabled;$('#settingsMemory').checked=s.memory_enabled;$('#settingsTemperature').value=s.temperature;$('#maxOutputTokens').value=s.max_output_tokens||512;$('#systemPrompt').value=s.system_prompt||'';$('#imageModel').value=(s.provider.type==='gemini'&&(!s.image_model||s.image_model==='dall-e-3'))?'gemini-2.5-flash-image':(s.image_model||'dall-e-3');$('#themeSelect').value=s.theme;document.documentElement.dataset.theme=s.theme;providerType=s.provider.type;$('#providerType').value=s.provider.type;$('#providerUrl').value=s.provider.base_url;$('#providerPreset').value=s.provider.preset||'custom';$('#providerKey').placeholder=s.provider.has_api_key?'Saved key exists · blank keeps it':'API key (required for hosted providers)';$('#uploadHint').textContent=`${s.max_upload_mb} MB / file · up to ${s.max_files_per_turn} files`;uiPrefs={enter_to_send:s.enter_to_send!==false,compact_mode:!!s.compact_mode,default_agent:s.default_agent!==false,auto_scroll:s.auto_scroll!==false};$('#enterToSend').checked=uiPrefs.enter_to_send;$('#compactMode').checked=uiPrefs.compact_mode;$('#defaultAgent').checked=uiPrefs.default_agent;$('#autoScroll').checked=uiPrefs.auto_scroll;$('#agentToggle').checked=uiPrefs.default_agent;document.body.classList.toggle('compact-mode',uiPrefs.compact_mode);$('#harnessModeToggle').checked=!!s.harness_mode;$('#deviceIdentityLabel').textContent=s.is_owner_device?'Owner device':'Paired device';$('#deviceIdentityInfo').textContent='Device ID: '+s.device_id+' · '+(s.is_owner_device?'Owns worldwide access credentials':'This device has its own private workspace and MCP configuration');document.querySelectorAll('.owner-only').forEach(el=>el.hidden=!s.is_owner_device);if(s.is_owner_device)await loadPairedDevices();await loadMcpServers();await loadNetworkStatus()}
async function saveSettings(){let payload={memory_enabled:$('#settingsMemory').checked,temperature:Number($('#settingsTemperature').value),max_output_tokens:Number($('#maxOutputTokens').value),system_prompt:$('#systemPrompt').value,theme:$('#themeSelect').value,image_model:$('#imageModel').value.trim(),enter_to_send:$('#enterToSend').checked,compact_mode:$('#compactMode').checked,default_agent:$('#defaultAgent').checked,auto_scroll:$('#autoScroll').checked,provider:{type:$('#providerType').value,preset:$('#providerPreset').value,base_url:$('#providerUrl').value.trim(),api_key:$('#providerKey').value}};let r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok){alert(await r.text());return}providerType=payload.provider.type;uiPrefs={enter_to_send:payload.enter_to_send,compact_mode:payload.compact_mode,default_agent:payload.default_agent,auto_scroll:payload.auto_scroll};$('#agentToggle').checked=uiPrefs.default_agent;document.body.classList.toggle('compact-mode',uiPrefs.compact_mode);$('#memoryToggle').checked=payload.memory_enabled;document.documentElement.dataset.theme=payload.theme;$('#providerKey').value='';$('#modal').classList.remove('open');await loadModels()}

async function testProvider(){let b=$('#testProvider');b.disabled=true;$('#providerTestResult').textContent='Testing…';try{let payload={provider:{type:$('#providerType').value,base_url:$('#providerUrl').value.trim(),api_key:$('#providerKey').value}};let r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok)throw Error(await r.text());let h=await fetch('/api/health'),d=await h.json();if(!d.ok)throw Error(d.error);$('#providerTestResult').textContent='Connected ✓';}catch(e){$('#providerTestResult').textContent='Failed: '+e.message.slice(0,100)}finally{b.disabled=false}}
async function loadMcpServers(){const r=await fetch('/api/mcp/servers');if(!r.ok)return;const items=await r.json();$('#mcpServers').innerHTML=items.map(x=>`<div class="project-line mcp-line"><span><b>${esc(x.name)}</b> · ${esc(x.transport)} · ${x.enabled?'enabled':'disabled'}</span><small>${esc(x.transport==='stdio'?x.command:x.url)} · ${x.has_env||x.has_headers?'credentials configured':''}</small><div><button data-mcp-test="${x.id}">Test</button><button data-mcp-toggle="${x.id}" data-enabled="${x.enabled}">${x.enabled?'Disable':'Enable'}</button><button data-mcp-delete="${x.id}">Remove</button></div></div>`).join('')||'<p class="muted">No MCP servers connected.</p>';document.querySelectorAll('[data-mcp-test]').forEach(b=>b.onclick=async()=>{b.disabled=true;b.textContent='Testing…';try{let r=await fetch('/api/mcp/servers/'+b.dataset.mcpTest+'/test',{method:'POST'}),d=await r.json();if(!r.ok)throw Error(d.detail||'Connection failed');alert(`Connected. ${d.tool_count} tools: ${d.tools.join(', ')}`)}catch(e){alert(e.message)}finally{b.disabled=false;b.textContent='Test'}});document.querySelectorAll('[data-mcp-toggle]').forEach(b=>b.onclick=async()=>{await fetch('/api/mcp/servers/'+b.dataset.mcpToggle,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:b.dataset.enabled!=='true'})});loadMcpServers()});document.querySelectorAll('[data-mcp-delete]').forEach(b=>b.onclick=async()=>{if(confirm('Remove this MCP server?')){await fetch('/api/mcp/servers/'+b.dataset.mcpDelete,{method:'DELETE'});loadMcpServers()}})}
async function addMcpServer(){try{const transport=$('#mcpTransport').value,config=transport==='stdio'?{command:$('#mcpCommand').value.trim(),args:JSON.parse($('#mcpArgs').value||'[]'),env:JSON.parse($('#mcpEnv').value||'{}')}:{url:$('#mcpUrl').value.trim(),headers:JSON.parse($('#mcpHeaders').value||'{}')};const r=await fetch('/api/mcp/servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#mcpName').value.trim(),transport,config})});if(!r.ok)throw Error(await r.text());$('#mcpName').value='';await loadMcpServers()}catch(e){alert('Could not add MCP server: '+e.message)}}
async function showMemories(){let r=await fetch('/api/memories'),items=await r.json();$('#memoryItems').innerHTML=items.map(m=>`<div class="memory-item"><textarea data-memory="${m.id}" rows="3">${esc(m.content)}</textarea><div><small>${esc(m.category)}</small><button data-memory-save="${m.id}">Save</button><button data-memory-delete="${m.id}">Delete</button></div></div>`).join('')||'<p class="muted">No saved memories yet. Add one below.</p>';document.querySelectorAll('[data-memory-save]').forEach(b=>b.onclick=async()=>{let id=b.dataset.memorySave,content=$(`[data-memory="${id}"]`).value;let r=await fetch('/api/memories/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,category:'general'})});if(!r.ok)alert(await r.text());else showMemories()});document.querySelectorAll('[data-memory-delete]').forEach(b=>b.onclick=async()=>{await fetch('/api/memories/'+b.dataset.memoryDelete,{method:'DELETE'});showMemories()})}
async function addMemory(){let content=$('#newMemory').value.trim();if(!content)return;let r=await fetch('/api/memories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,category:'user-added'})});if(!r.ok){alert(await r.text());return}$('#newMemory').value='';showMemories()}

let engineerProjectId=localStorage.getItem('canarry-engineer-project')||null, engineerAbort=null, engineerBusy=false, lastEngineerTask=localStorage.getItem('canarry-engineer-last-task')||'';
function engineerLog(text,kind="info"){
  const line=document.createElement("div");line.className="engineer-log "+kind;line.textContent=text;
  const copy=document.createElement("button");copy.className="copy-btn inline-copy";copy.type="button";copy.textContent="▢";copy.title="Copy this output";copy.onclick=()=>copyText(text,copy);line.appendChild(copy);
  $("#engineerOutput").appendChild(line);$("#engineerOutput").scrollTop=$("#engineerOutput").scrollHeight;
}
async function updateEngineerCapabilities(){
  const model=$("#modelSelect").value;
  $("#engineerModelLabel").textContent=model?`Model: ${model}`:"No model selected";
  if(!model){$("#engineerThink").disabled=true;$("#engineerCapability").textContent="Choose a model first.";return}
  try{
    const r=await fetch("/api/model-capabilities/"+encodeURIComponent(model)),d=await r.json();
    const supported=providerType==="ollama"&&d.thinking===true;
    $("#engineerThink").disabled=!supported;
    if(!supported)$("#engineerThink").checked=false;
    $("#engineerCapability").textContent=supported?"This model reports thinking capability. Enable it for this task.":"The selected model does not report a supported thinking capability; the option is unavailable. Web search can still be used by the agent.";
  }catch(e){$("#engineerThink").disabled=true;$("#engineerCapability").textContent="Could not verify model thinking support."}
}
async function loadEngineerProjects(selectId=engineerProjectId){
  try{
    const r=await fetch("/api/engine/projects");if(!r.ok)throw Error(await r.text());const projects=await r.json();
    $("#engineerProjectSelect").innerHTML='<option value="">Choose a project</option>'+projects.map(p=>`<option value="${p.id}">${esc(p.name)} · ${p.files} files</option>`).join("");
    if(selectId&&projects.some(p=>p.id===selectId)){engineerProjectId=selectId;$("#engineerProjectSelect").value=selectId;await loadEngineerProjectFiles()}
    else if(selectId){engineerProjectId=null;localStorage.removeItem("canarry-engineer-project");$("#engineerRun").disabled=true;$("#engineerExport").disabled=true;$("#engineerProjectStatus").textContent="Choose or import a project."}
  }catch(e){engineerLog("Could not load imported projects: "+e.message,"error")}
}
async function loadEngineerProjectFiles(){
  if(!engineerProjectId)return;
  const r=await fetch(`/api/engine/project/${engineerProjectId}/files?recursive=true`);
  if(!r.ok)throw Error(await r.text());const d=await r.json();
  $("#engineerFileList").innerHTML=d.files.slice(0,5000).map(x=>`<div>${esc(x.path)}${x.directory?"/":""}</div>`).join("")||"<p>No files found.</p>";
  $("#engineerProjectStatus").textContent=`Selected project · ${d.files.filter(x=>!x.directory).length} files`;
  $("#engineerRun").disabled=false;$("#engineerExport").disabled=false;$("#engineerReload").disabled=false;
}
async function openEngineer(){
  $("#engineerModal").classList.add("open");$("#engineerModal").setAttribute("aria-hidden","false");
  await updateEngineerCapabilities();await loadEngineerProjects();
  if(!engineerProjectId)$("#engineerRun").disabled=true;
}
function closeEngineer(){if(engineerBusy&&!confirm("The agent is working. Close the workspace and stop the active request?"))return;if(engineerAbort)engineerAbort.abort();$("#engineerModal").classList.remove("open");$("#engineerModal").setAttribute("aria-hidden","true")}
async function importEngineerArchive(file){
  if(!file)return;
  $("#engineerProjectStatus").textContent="Extracting "+file.name+"…";
  $("#engineerRun").disabled=true;$("#engineerExport").disabled=true;
  const fd=new FormData();fd.append("file",file);
  try{
    const r=await fetch("/api/engine/import",{method:"POST",body:fd});
    if(!r.ok)throw Error(await r.text());
    const d=await r.json();engineerProjectId=d.id;localStorage.setItem('canarry-engineer-project',d.id);
    $("#engineerProjectStatus").textContent=`${file.name} · ${d.files} files imported`;
    await loadEngineerProjects(d.id);
    $("#engineerRun").disabled=false;$("#engineerExport").disabled=false;$("#engineerReload").disabled=false;
    $("#engineerOutput").innerHTML="";engineerLog("Project imported into this device's private workspace.","success");
    engineerLog("Source files are ready for inspection. Select a task and start the agent.");
  }catch(e){$("#engineerProjectStatus").textContent="Import failed";engineerLog(e.message,"error")}
  finally{$("#engineerArchive").value=""}
}
async function runEngineer(preserveOutput=false){
  if(engineerBusy){return}
  if(!engineerProjectId){alert("Import a project archive first.");return}
  const task=$("#engineerTask").value.trim()||lastEngineerTask,model=$("#modelSelect").value;
  if(!task||!model){alert("Enter a task and select a model.");return}
  $("#engineerTask").value=task;lastEngineerTask=task;localStorage.setItem('canarry-engineer-last-task',task);
  $("#engineerRetry").disabled=false;$("#engineerReuse").disabled=false;
  engineerBusy=true;engineerAbort=new AbortController();$("#engineerRun").hidden=true;$("#engineerStop").hidden=false;
  const state=$("#engineerRunState");if(state){state.textContent="Working · model is inspecting the project";state.dataset.state="working"}
  if(!preserveOutput)$("#engineerOutput").innerHTML="";
  engineerLog((preserveOutput?"Retrying":"Starting")+" project engineering task with "+model+"…","success");
  try{
    const r=await fetch(`/api/engine/project/${engineerProjectId}/agent`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({task,model,think:$("#engineerThink").checked,web_search:$("#engineerWeb").checked}),signal:engineerAbort.signal});
    if(!r.ok){let body=await r.text();try{const parsed=JSON.parse(body);body=parsed.detail||parsed.error||parsed.message||body}catch{}throw Error(body||`Request failed (${r.status}).`)}
    const reader=r.body.getReader(),decoder=new TextDecoder();let buffer="",current=null;
    while(true){
      const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});
      const parts=buffer.split("\n\n");buffer=parts.pop();
      for(const part of parts){
        const line=part.split("\n").find(x=>x.startsWith("data: "));if(!line)continue;
        const ev=JSON.parse(line.slice(6));
        if(ev.type==="clear_response"){
          if(current){current.remove();current=null}
        }else if(ev.type==="token"){
          if(!current){current=document.createElement("pre");current.className="engineer-token";$("#engineerOutput").appendChild(current)}
          current.textContent+=(ev.text||"");$("#engineerOutput").scrollTop=$("#engineerOutput").scrollHeight;
        }else if(ev.type==="tool"){
          current=null;const failed=!!(ev.result&&ev.result.error);const detail=document.createElement("details");detail.className="engineer-tool"+(failed?" tool-failed":"");detail.open=failed;
          const summary=document.createElement("summary");summary.textContent=(failed?"Tool error · ":"Tool result · ")+ev.name;detail.appendChild(summary);
          const pre=document.createElement("pre");const output=JSON.stringify({arguments:ev.arguments,result:ev.result},null,2);pre.textContent=output;const copy=document.createElement("button");copy.className="copy-btn code-copy";copy.type="button";copy.textContent="▢ Copy output";copy.onclick=()=>copyText(output,copy);pre.appendChild(copy);detail.appendChild(pre);$("#engineerOutput").appendChild(detail);if(failed)engineerLog(String(ev.result.error),"error");
        }else if(ev.type==="notice"){current=null;engineerLog(ev.message,"notice")}
        else if(ev.type==="error"){current=null;throw Error(ev.message||ev.error||JSON.stringify(ev)||"The provider returned an unspecified error.")}
        else if(ev.type==="done"){
          if(current&&!current.querySelector('.code-copy')){const raw=current.textContent;const copy=document.createElement('button');copy.className='copy-btn code-copy';copy.type='button';copy.textContent='⧉ Copy response';copy.onclick=()=>copyText(raw,copy);current.appendChild(copy)}
          current=null;engineerLog("Agent finished this task.","success");if($("#engineerRunState")){$("#engineerRunState").textContent="Finished";$("#engineerRunState").dataset.state="done"}
        }
      }
    }
  }catch(e){if(e.name==="AbortError"){engineerLog("Stopped at your request. Changes already written remain in the project.","notice");if($("#engineerRunState")){$("#engineerRunState").textContent="Stopped";$("#engineerRunState").dataset.state="stopped"}}else{const message=e.message||String(e)||"Unknown provider error. Check the server terminal for details.";engineerLog("Agent error: "+message,"error");if($("#engineerRunState")){$("#engineerRunState").textContent="Failed · see activity below";$("#engineerRunState").dataset.state="error"}}}
  finally{engineerBusy=false;engineerAbort=null;$("#engineerRun").hidden=false;$("#engineerStop").hidden=true;$("#engineerRun").disabled=!engineerProjectId;if($("#engineerRunState")&&$("#engineerRunState").dataset.state==="working"){$("#engineerRunState").textContent="Finished";$("#engineerRunState").dataset.state="done"}}
}
async function retryEngineerTask(){if(!lastEngineerTask)return;$("#engineerTask").value=lastEngineerTask;await runEngineer(true)}
function reuseEngineerPrompt(){if(!lastEngineerTask)return;$("#engineerTask").value=lastEngineerTask;$("#engineerTask").focus();$("#engineerTask").style.height='auto';$("#engineerTask").style.height=Math.min($("#engineerTask").scrollHeight,420)+'px'}
async function copyEngineerOutput(){const text=$("#engineerOutput").innerText||'';await copyText(text,$("#engineerCopyAll"))}
async function exportEngineerProject(){
  if(!engineerProjectId)return;
  const format=$("#engineerExportFormat").value;$("#engineerExport").disabled=true;
  try{
    const r=await fetch(`/api/engine/project/${engineerProjectId}/export?format=${encodeURIComponent(format)}`);
    if(!r.ok)throw Error(await r.text());
    const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download=({"tar.gz":"project.tar.gz","7z":"project.7z",tar:"project.tar",rar:"project.rar",zip:"project.zip"})[format];
    document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
    engineerLog("Exported updated project as "+format.toUpperCase()+".","success");
  }catch(e){engineerLog("Export failed: "+e.message,"error")}
  finally{$("#engineerExport").disabled=false}
}

$('#voiceMic').onclick=startVoiceInput;$('#voiceOutput').onclick=()=>{voiceOutputEnabled=!voiceOutputEnabled;localStorage.setItem('canarry-voice-output',voiceOutputEnabled?'1':'0');if(!voiceOutputEnabled&&'speechSynthesis' in window)speechSynthesis.cancel();updateVoiceControls()};updateVoiceControls();$('#sendBtn').onclick=send;$('#prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&uiPrefs.enter_to_send){e.preventDefault();send()}});$('#prompt').addEventListener('input',e=>{e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,190)+'px'});$('#newChat').onclick=newChat;$('#clearBtn').onclick=newChat;document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('#prompt').value=b.dataset.prompt;send()});$('#agentToggle').onchange=updateStats;$('#modelSelect').onchange=()=>checkModelCapabilities($('#modelSelect').value);$('#fileButton').onclick=()=>$('#fileInput').click();$('#fileInput').onchange=e=>uploadFiles([...e.target.files]);$('#settingsBtn').onclick=async()=>{$('#modal').classList.add('open');await showMemories();await loadProjects();await loadNetworkStatus()};$('#modalClose').onclick=closeSettings;$('#modal').addEventListener('click',e=>{if(e.target===$('#modal'))closeSettings()});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('#modal').classList.contains('open'))closeSettings()});$('#saveSettings').onclick=saveSettings;$('#addMemory').onclick=addMemory;$('#addMcp').onclick=addMcpServer;$('#mcpTransport').onchange=()=>{const stdio=$('#mcpTransport').value==='stdio';$('#mcpStdioFields').hidden=!stdio;$('#mcpHttpFields').hidden=stdio};$('#testProvider').onclick=testProvider;$('#imageBtn').onclick=generateImage;$('#scrollDown').onclick=scrollLatest;$('#chatArea').addEventListener('scroll',updateScrollButton);$('#newProject').onclick=async()=>{const name=prompt('New project folder name');if(!name?.trim())return;const r=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.trim()})});if(!r.ok){alert('Could not create project: '+await r.text());return}const project=await r.json();activeProject=project.id;await loadProjects();if(chatId)await fetch('/api/chats/'+chatId+'/project',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:activeProject})});await refreshChats();renderHistory()};$('#createProject').onclick=createProject;$('#projectName').addEventListener('keydown',e=>{if(e.key==='Enter')createProject()});$('#providerType').onchange=()=>{const t=$('#providerType').value;const defaults={ollama:'http://127.0.0.1:11434','openai-compatible':'https://api.openai.com/v1',anthropic:'https://api.anthropic.com/v1',gemini:'https://generativelanguage.googleapis.com/v1beta'};$('#providerUrl').value=defaults[t]||$('#providerUrl').value;$('#providerPreset').value='custom'};$('#themeSelect').onchange=()=>document.documentElement.dataset.theme=$('#themeSelect').value;
$('#hideLeft').onclick=()=>setPanel('left',true);$('#hideRight').onclick=()=>setPanel('right',true);$('#showLeft').onclick=()=>setPanel('left',false);$('#showRight').onclick=()=>setPanel('right',false);if(localStorage.getItem('canarry-left-collapsed')==='1')setPanel('left',true);if(localStorage.getItem('canarry-right-collapsed')==='1')setPanel('right',true);
const presets={openai:'https://api.openai.com/v1',openrouter:'https://openrouter.ai/api/v1',groq:'https://api.groq.com/openai/v1',together:'https://api.together.xyz/v1',deepseek:'https://api.deepseek.com/v1',fireworks:'https://api.fireworks.ai/inference/v1',mistral:'https://api.mistral.ai/v1',xai:'https://api.x.ai/v1','local-vllm':'http://127.0.0.1:8000/v1'};$('#providerPreset').onchange=()=>{const v=$('#providerPreset').value;if(presets[v]){$('#providerType').value='openai-compatible';$('#providerUrl').value=presets[v]}};
$('#exportAllChats').onclick=exportAllChats;$('#exportAllChatsSettings').onclick=exportAllChats;$('#refreshNetwork').onclick=loadNetworkStatus;$('#saveNetworkAuth').onclick=saveNetworkAuth;$('#startTunnel').onclick=startPublicTunnel;$('#stopTunnel').onclick=stopPublicTunnel;$('#tunnelProvider').onchange=loadNetworkStatus;$('#saveHarnessMode').onclick=saveHarnessMode;$('#createPairCode').onclick=createPairCode;$('#saveTunnelCredential').onclick=saveTunnelCredential;$('#clearTunnelCredential').onclick=clearTunnelCredential;
$('#engineerProjectSelect').onchange=async e=>{engineerProjectId=e.target.value||null;if(engineerProjectId)localStorage.setItem('canarry-engineer-project',engineerProjectId);else localStorage.removeItem('canarry-engineer-project');if(engineerProjectId){try{await loadEngineerProjectFiles()}catch(err){engineerLog(err.message,"error")}}else{$("#engineerRun").disabled=true;$("#engineerExport").disabled=true;$("#engineerFileList").innerHTML="";$("#engineerProjectStatus").textContent="No project selected."}};$('#openProjectEngineer').onclick=openEngineer;$('#closeProjectEngineer').onclick=closeEngineer;$('#engineerModal').addEventListener('click',e=>{if(e.target===$('#engineerModal'))closeEngineer()});$('#engineerArchive').onchange=e=>importEngineerArchive(e.target.files?.[0]);$('#engineerRun').onclick=runEngineer;$('#engineerStop').onclick=()=>engineerAbort?.abort();$('#engineerRetry').onclick=retryEngineerTask;$('#engineerReuse').onclick=reuseEngineerPrompt;$('#engineerReload').onclick=async()=>{try{await loadEngineerProjectFiles();engineerLog('Project file list reloaded.','success')}catch(e){engineerLog('Reload failed: '+e.message,'error')}};$('#engineerCopyAll').onclick=copyEngineerOutput;$('#engineerClearOutput').onclick=()=>{$('#engineerOutput').innerHTML='';if($('#engineerRunState')){$('#engineerRunState').textContent='Ready';$('#engineerRunState').dataset.state='idle'}};$('#engineerExport').onclick=exportEngineerProject;$('#modelSelect').addEventListener('change',updateEngineerCapabilities);
if(lastEngineerTask){$('#engineerTask').value=lastEngineerTask;$('#engineerRetry').disabled=false;$('#engineerReuse').disabled=false}
ensureDevicePaired().then(ok=>{if(!ok){document.body.innerHTML='<main style="padding:3rem;max-width:40rem;margin:auto"><h2>Device pairing required</h2><p>Ask the owner device to generate a one-time pairing code in Settings → Device identity & privacy, then reload this page.</p></main>';return}loadSettings().then(()=>loadModels());refreshChats();loadProjects();setInterval(loadModels,90000)});
