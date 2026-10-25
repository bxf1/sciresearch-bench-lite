// Exercise the installed native Pi summarizer and Anthropic SDK against a
// loopback-only prototype relay. All inputs and upstream responses are synthetic.
import { generateSummaryWithUsage } from '/home/researcher/.nvm/versions/node/v22.23.4/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/compaction/compaction.js';

const model = {
  id: 'deepseek-flash', name: 'offline probe', api: 'anthropic-messages',
  provider: 'harbor-endpoint', baseUrl: process.argv[2], reasoning: false,
  input: ['text'], contextWindow: 128000, maxTokens: 16384,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
};
const token = process.env.BENCH_RELAY_KEY;
const messages = [{ role: 'user', content: [{ type: 'text', text: 'Synthetic conversation: user requests OK; assistant responds OK. No scientific data.' }], timestamp: 0 }];
try {
  const result = await generateSummaryWithUsage(messages, model, 16384, token,
    undefined, undefined, undefined, process.argv[3] === 'update' ? 'Synthetic previous summary.' : undefined,
    'off', undefined, undefined, { enabled: false });
  console.log(JSON.stringify({ status: 'success', text: result.text, usage: result.usage }));
} catch (error) {
  console.log(JSON.stringify({ status: 'rejected', error: String(error.message) }));
  process.exitCode = 2;
}
