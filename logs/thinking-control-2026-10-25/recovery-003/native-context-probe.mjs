import fs from 'node:fs';
const base='/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent';
const {createAgentSession}=await import(base+'/dist/core/sdk.js');
const {SessionManager}=await import(base+'/dist/core/session-manager.js');
const {SettingsManager}=await import(base+'/dist/core/settings-manager.js');
const {streamSimple}=await import(base+'/node_modules/@earendil-works/pi-ai/dist/compat.js');
const model={id:'deepseek-flash',name:'Native context handoff probe',api:'anthropic-messages',provider:'probe',baseUrl:process.argv[2],reasoning:false,input:['text'],contextWindow:128000,maxTokens:16384,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
fs.mkdirSync('/tmp/session-probe',{recursive:true});
fs.writeFileSync('/tmp/session-probe/models.json',JSON.stringify({providers:{probe:{baseUrl:model.baseUrl,api:model.api,apiKey:'BENCH_RELAY_KEY',models:[{id:model.id,name:model.name,contextWindow:128000,maxTokens:16384}]}}}));
const manager=SessionManager.inMemory('/tmp/session-probe');
const make=(stopReason,content,output,input,timestamp=Date.now())=>({role:'assistant',api:model.api,provider:model.provider,model:model.id,content,stopReason,rawStopReason:stopReason==='length'?'max_tokens':'end_turn',timestamp,usage:{input,output,cacheRead:0,cacheWrite:0,totalTokens:input+output,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
for(let i=0;i<6;i++){
 manager.appendMessage({role:'user',content:[{type:'text',text:'Historical synthetic material '+('data '.repeat(15000))}],timestamp:Date.now()-10000});
 manager.appendMessage(make('stop',[{type:'text',text:'Historical acknowledgement'}],2,100,Date.now()-10000));
}
const {session}=await createAgentSession({cwd:'/tmp/session-probe',agentDir:'/tmp/session-probe',model,thinkingLevel:'off',tools:[],settingsManager:SettingsManager.inMemory({compaction:{enabled:true},retry:{enabled:false}}),sessionManager:manager});
const events=[],responses=[],wires=[];let injected=false,calls=0;
session.subscribe(e=>{
 if(['agent_end','compaction_start','compaction_end'].includes(e.type))events.push({type:e.type,reason:e.reason,willRetry:e.willRetry,error:e.errorMessage,hasResult:!!e.result});
 if(e.type==='message_end'&&e.message.role==='assistant'){
  const m=e.message;responses.push({stopReason:m.stopReason,rawStopReason:m.rawStopReason,output:m.usage.output,blocks:m.content.map(c=>c.type),thinkingChars:m.content.filter(c=>c.type==='thinking').reduce((n,c)=>n+c.thinking.length,0),text:m.content.filter(c=>c.type==='text').map(c=>c.text).join('')});
 }
});
session.agent.streamFunction=async(m,ctx,options)=>{
 if(!injected){
  injected=true;
  // Synthetic usage metadata places the unchanged 128000 window at its boundary.
  // This fixture is not an API request and never contributes to measured probe usage.
  const value=make('length',[{type:'thinking',thinking:'Synthetic unfinished scratchwork: the pending user request is to respond OK.'}],4096,124100);
  return {async *[Symbol.asyncIterator](){yield {type:'done',reason:'length',message:value};},async result(){return value;}};
 }
 if(++calls>12)throw Error('Bounded synthetic context probe exceeded 12 real calls');
 const summary=ctx.systemPrompt.includes('summariz')||ctx.systemPrompt.includes('summary');
 return streamSimple(m,ctx,{...options,apiKey:process.env.BENCH_RELAY_KEY,onPayload(p){wires.push({summary,requested_max_tokens:p.max_tokens,last_role:p.messages.at(-1)?.role,user_messages:p.messages.filter(x=>x.role==='user').length,prior_thinking_blocks:p.messages.flatMap(x=>Array.isArray(x.content)?x.content:[]).filter(b=>b.type==='thinking').length});}});
};
try{
 await session.prompt('This is a synthetic transport check. Respond only OK when ready.');
 if(wires[0]?.requested_max_tokens!==1)throw Error('Native client did not hit the synthetic one-token boundary');
 if(!events.some(e=>e.type==='compaction_end'&&e.hasResult&&e.willRetry&&!e.error))throw Error('Native compaction did not complete and resume');
 if(!responses.at(-1)?.text.includes('OK')||responses.at(-1).stopReason!=='stop')throw Error('Missing final answer after compaction');
 if(!wires.some((w,i)=>i>0&&!w.summary&&w.requested_max_tokens>=4096))throw Error('Post-compaction research cap did not recover');
 if(responses.some(r=>r.stopReason==='error'))throw Error('Native response error');
 console.log(JSON.stringify({status:'passed',real_native_agent_session:true,scientific_data_accessed:false,synthetic_initial_assistant_usage:{input:124100,output:4096,charged_to_relay:false},events,responses,wires,real_calls:calls}));
}catch(e){console.log(JSON.stringify({status:'failed',error:String(e.message),real_native_agent_session:true,scientific_data_accessed:false,events,responses,wires,real_calls:calls}));process.exitCode=2;}
finally{session.dispose();}
