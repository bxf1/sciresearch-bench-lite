import {runAgentLoop} from '/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js';
import {streamSimple} from '/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/compat.js';
const model={id:'deepseek-flash',name:'thinking continuation probe',api:'anthropic-messages',provider:'harbor-endpoint',baseUrl:process.argv[2],reasoning:false,input:['text'],contextWindow:128000,maxTokens:16384,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const prompt={role:'user',content:[{type:'text',text:'Count the nonnegative integer triples (x,y,z) satisfying x + 2*y + 3*z = 600. Think carefully, then call echo with the decimal count. After its result respond only OK.'}],timestamp:0};
const records=[],wires=[];let calls=0,echoed=false;
const tool={name:'echo',description:'Return the supplied text unchanged.',parameters:{type:'object',properties:{text:{type:'string'}},required:['text']},execute:async(id,args)=>{if(args.text!=='30301')throw Error('Wrong synthetic count');echoed=true;return {content:[{type:'text',text:args.text}],details:{}};}};
try{
 await runAgentLoop([prompt],{systemPrompt:'You are verifying a tool transport. Follow the requested echo workflow.',messages:[],tools:[tool]},
 {model,convertToLlm:async m=>m,apiKey:process.env.BENCH_RELAY_KEY},e=>{
  if(e.type==='message_end'&&e.message.role==='assistant'){const m=e.message;records.push({stopReason:m.stopReason,rawStopReason:m.rawStopReason,output:m.usage.output,error:m.errorMessage??null,blocks:m.content.map(c=>c.type),thinkingChars:m.content.filter(c=>c.type==='thinking').reduce((n,c)=>n+c.thinking.length,0),text:m.content.filter(c=>c.type==='text').map(c=>c.text).join('')});}
 },undefined,(m,ctx,options)=>{
  if(calls>=6)throw Error('Synthetic probe request bound exceeded');
  const cap=calls++===0?256:4096;
  return streamSimple(m,ctx,{...options,maxTokens:cap,onPayload(p){wires.push({requested_max_tokens:p.max_tokens,user_messages:p.messages.filter(m=>m.role==='user').length,prior_thinking_blocks:p.messages.flatMap(m=>Array.isArray(m.content)?m.content:[]).filter(b=>b.type==='thinking').length,last_role:p.messages.at(-1)?.role});}});
 });
 if(records[0]?.stopReason!=='length'||records[0].blocks.join(',')!=='thinking'||!records[0].thinkingChars)throw Error('Synthetic first request did not produce targeted truncation');
 if(records.length<3||wires[1].prior_thinking_blocks<1||!echoed||!records.at(-1).text.includes('OK'))throw Error('Missing automatic continuation, carried thinking, tool result or final answer');
 if(records.some(r=>r.stopReason==='error'))throw Error('Native continuation error');
 console.log(JSON.stringify({status:'passed',records,wires,first_request_cap_for_probe_only:256,scientific_data_accessed:false}));
}catch(e){console.log(JSON.stringify({status:'failed',error:String(e.message),records,wires}));process.exitCode=2;}
