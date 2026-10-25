import assert from 'node:assert/strict';
import {runAgentLoop} from './agent-loop.test.mjs';
const model={id:'deepseek-flash',provider:'test',api:'anthropic-messages',maxTokens:4096};
const msg=(stopReason,content)=>({role:'assistant',api:model.api,provider:model.provider,model:model.id,
 content,stopReason,timestamp:0,usage:{input:1,output:stopReason==='length'?4096:1,cacheRead:0,cacheWrite:0,totalTokens:2,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
const thought={type:'thinking',thinking:'Synthetic partial reasoning',thinkingSignature:'synthetic'};
const prompt={role:'user',content:[{type:'text',text:'Original synthetic task'}],timestamp:0};
const records=[];
async function check(name,replies,expectedCalls,expectedExecutions=0){
 let calls=0,executions=0; const seen=[],events=[];
 const tool={name:'echo',description:'Echo',parameters:{type:'object',properties:{text:{type:'string'}},required:['text']},execute:async()=>{executions++;return {content:[{type:'text',text:'ok'}],details:{}};}};
 const stream=async(m,ctx,options)=>{seen.push(JSON.parse(JSON.stringify(ctx)));assert.ok(calls<replies.length,'unexpected continuation');const value=replies[calls++];return {async *[Symbol.asyncIterator](){yield {type:'done',reason:value.stopReason,message:value};},async result(){return value;}};};
 await runAgentLoop([prompt],{systemPrompt:'unchanged system',messages:[],tools:[tool]},
  {model,convertToLlm:async m=>m},e=>events.push(e),undefined,stream);
 assert.equal(calls,expectedCalls);assert.equal(executions,expectedExecutions);
 assert.equal(events.filter(e=>e.type==='agent_end').length,1);
 for(const c of seen){assert.equal(c.systemPrompt,'unchanged system');assert.equal(c.messages.filter(m=>m.role==='user').length,1);assert.deepEqual(c.messages[0],prompt);}
 if(expectedCalls>1&&replies[0].content.length===1&&replies[0].content[0].type==='thinking')assert.deepEqual(seen[1].messages.at(-1).content,[thought]);
 records.push({name,calls,executions,status:'passed'});
}
const final=msg('stop',[{type:'text',text:'OK'}]);
await check('thinking truncation then valid tool and answer',[msg('length',[thought]),msg('toolUse',[{type:'toolCall',id:'echo-1',name:'echo',arguments:{text:'ok'}}]),final],3,1);
await check('multiple truncations retain shared context',[msg('length',[thought]),msg('length',[thought]),final],3);
await check('budget error ends continuation',[msg('length',[thought]),{...msg('error',[]),errorMessage:'output_budget_exhausted'}],2);
await check('ordinary answer unchanged',[final],1);
await check('ordinary thinking end unchanged',[msg('stop',[thought])],1);
await check('empty thinking does not spin',[msg('length',[{type:'thinking',thinking:''}])],1);
await check('text truncation unchanged',[msg('length',[{type:'text',text:'partial'}])],1);
await check('truncated tool arguments never execute',[msg('length',[thought,{type:'toolCall',id:'partial-tool',name:'echo',arguments:{text:'partial'}}]),final],2,0);
console.log(JSON.stringify({status:'passed',synthetic_only:true,cases:records}));
