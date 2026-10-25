import { streamSimple } from '/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/compat.js';
const model={id:'deepseek-flash',name:'thinking-max plumbing probe',api:'anthropic-messages',provider:'harbor-endpoint',baseUrl:process.argv[2],reasoning:false,input:['text'],contextWindow:128000,maxTokens:16384,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const context={systemPrompt:'You are verifying a tool transport. Follow the requested echo workflow.',messages:[{role:'user',content:[{type:'text',text:'Call the echo tool with text OK. After its result, respond only OK.'}],timestamp:0}],tools:[{name:'echo',description:'Return the supplied text unchanged.',parameters:{type:'object',properties:{text:{type:'string'}},required:['text']}}]};
const records=[];
try{
 for(let turn=0;turn<3;turn++){
  let wire;
  const result=await streamSimple(model,context,{apiKey:process.env.BENCH_RELAY_KEY,maxTokens:4096,onPayload(p){wire={priorThinkingBlocks:p.messages.flatMap(m=>Array.isArray(m.content)?m.content:[]).filter(b=>b.type==='thinking').length,requestedThinking:p.thinking??null,tools:p.tools?.length};}}).result();
  const calls=result.content.filter(b=>b.type==='toolCall');
  records.push({turn,wire,stopReason:result.stopReason,errorMessage:result.errorMessage??null,usage:result.usage,thinkingBlocks:result.content.filter(b=>b.type==='thinking').length,thinkingChars:result.content.filter(b=>b.type==='thinking').reduce((n,b)=>n+b.thinking.length,0),toolCalls:calls.map(c=>({name:c.name,arguments:c.arguments})),text:result.content.filter(b=>b.type==='text').map(b=>b.text).join('')});
  if(result.stopReason==='error'||result.stopReason==='aborted')throw Error('Native stream did not finish successfully');
  context.messages.push(result);
  if(!calls.length)break;
  for(const c of calls){if(c.name!=='echo'||c.arguments.text!=='OK')throw Error('Unexpected synthetic tool call');context.messages.push({role:'toolResult',toolCallId:c.id,toolName:c.name,content:[{type:'text',text:'OK'}],isError:false,timestamp:Date.now()});}
 }
 if(records.length<2||!records[0].toolCalls.length||records[1].wire.priorThinkingBlocks<1||!records.every(r=>r.thinkingBlocks>0)||!records.at(-1).text.includes('OK'))throw Error('Missing thinking, tool round-trip, or final answer');
 console.log(JSON.stringify({status:'passed',records}));
}catch(e){console.log(JSON.stringify({status:'failed',error:String(e.message),records}));process.exitCode=2;}
