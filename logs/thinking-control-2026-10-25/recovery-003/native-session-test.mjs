import assert from 'node:assert/strict';
import fs from 'node:fs';
const base='/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent';
const {createAgentSession}=await import(base+'/dist/core/sdk.js');
const {SessionManager}=await import(base+'/dist/core/session-manager.js');
const {SettingsManager}=await import(base+'/dist/core/settings-manager.js');
const {clampMaxTokensToContext}=await import(base+'/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js');
const model={id:'synthetic',provider:'probe',api:'anthropic-messages',name:'Synthetic',reasoning:false,input:['text'],contextWindow:128000,maxTokens:16384,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const make=(stopReason,content,output=1,input=1)=>({role:'assistant',api:model.api,provider:model.provider,model:model.id,content,stopReason,rawStopReason:stopReason==='length'?'max_tokens':'end_turn',timestamp:Date.now(),usage:{input,output,cacheRead:0,cacheWrite:0,totalTokens:input+output,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
const thought={type:'thinking',thinking:'Synthetic unfinished reasoning.'};
const final=()=>make('stop',[{type:'text',text:'OK'}],2);
fs.mkdirSync('/tmp/session-probe',{recursive:true});
fs.writeFileSync('/tmp/session-probe/models.json',JSON.stringify({providers:{probe:{baseUrl:'http://invalid.local',api:'anthropic-messages',apiKey:'synthetic-not-a-credential',models:[{id:'synthetic',name:'Synthetic',contextWindow:128000,maxTokens:16384}]}}}));
const results=[];
async function check(name,outputs,expectedCompaction,terminal="OK"){
 const manager=SessionManager.inMemory('/tmp/session-probe');
 // Actual text creates enough history to exercise native summary and cut-point handling.
 for(let i=0;i<6;i++){
  manager.appendMessage({role:'user',content:[{type:'text',text:'Synthetic historical material '+('data '.repeat(15000))}],timestamp:Date.now()});
  manager.appendMessage(make('stop',[{type:'text',text:'Historical acknowledgement'}],2,100));
 }
 const settings=SettingsManager.inMemory({compaction:{enabled:true},retry:{enabled:false}});
 const {session}=await createAgentSession({cwd:'/tmp/session-probe',agentDir:'/tmp/session-probe',model,thinkingLevel:'off',tools:[],settingsManager:settings,sessionManager:manager});
 const events=[],requests=[];let index=0,summaries=0;
 session.subscribe(e=>{if(['agent_end','compaction_start','compaction_end'].includes(e.type))events.push({type:e.type,reason:e.reason,willRetry:e.willRetry,error:e.errorMessage,hasResult:!!e.result});});
 session.agent.streamFunction=async(m,context,options)=>{
  assert.ok(requests.length<12,'No unbounded native request loop');
  await new Promise(resolve=>setTimeout(resolve,5));
  const summary=context.systemPrompt.includes('summariz')||context.systemPrompt.includes('summary');
  requests.push({summary,lastRole:context.messages.at(-1)?.role,clamped:clampMaxTokensToContext(m,context,m.maxTokens),messageCount:context.messages.length});
  const value=summary?(summaries++,make('stop',[{type:'text',text:'## Goal\nComplete the original synthetic task and respond OK.\n## Progress\nHistorical synthetic context reviewed.\n## Next Steps\nFinish the task.'}],30)):(assert.ok(index<outputs.length,'Unexpected research request'),outputs[index++]());
  return {async *[Symbol.asyncIterator](){yield {type:'done',reason:value.stopReason,message:value};},async result(){return value;}};
 };
 let error=null;
 try{
  await session.prompt('Finish the original synthetic task.');
  assert.equal(index,outputs.length);
  if(expectedCompaction)assert.equal(requests.at(-1).clamped,16384,'Compacted prefix must invalidate stale usage estimates');
  assert.equal(events.filter(e=>e.type==='compaction_end'&&e.hasResult&&e.willRetry).length,expectedCompaction);
  if(terminal==='OK'){
   assert.equal(session.agent.state.messages.at(-1)?.content.at(-1)?.text,'OK');
   await assert.rejects(session.agent.continue(),/Cannot continue from message role: assistant/);
  }else{
   assert.equal(session.agent.state.messages.at(-1)?.stopReason,terminal);
   assert.equal(events.filter(e=>e.type==='compaction_start').length,1);
  }
 }catch(e){error=String(e.message);}
 session.dispose();
 results.push({name,status:error?'failed':'passed',error,index,summaries,events,requests});
}
await check('full request cap continues without compaction',[()=>make('length',[thought],4096,100),final],0);
await check('context-clamped one token compacts then resumes',[()=>make('length',[thought],1,124100),final],1);
await check('consecutive full thought fragments then context clamp',[()=>make('length',[thought],4096,110000),()=>make('length',[thought],4096,124100),()=>make('length',[thought],1,124100),final],1);
await check('repeated context truncation retains native one-recovery bound',[()=>make('length',[thought],1,124100),()=>make('length',[thought],1,124100)],1,'length');
console.log(JSON.stringify({status:results.every(x=>x.status==='passed')?'passed':'failed',synthetic_only:true,real_native_agent_session:true,cases:results}));
if(results.some(x=>x.status==='failed'))process.exitCode=2;
