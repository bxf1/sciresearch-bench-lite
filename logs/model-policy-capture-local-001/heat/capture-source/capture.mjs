import { writeSync } from "node:fs";
function emit(fd, text) {
  const bytes = Buffer.from(text);
  let position = 0;
  while (position < bytes.length) position += writeSync(fd, bytes, position);
}
export default function (pi) {
  pi.on("before_provider_request", (event) => {
    try {
      const p = event.payload;
      if (p.model !== "deepseek-v4-pro" || p.stream !== true ||
          !Array.isArray(p.system) || !Array.isArray(p.tools)) {
        process.exit(71);
      }
      const record = {schema_version: 1, stage: "before_provider_request",
        model: p.model, stream: p.stream, requested_max_tokens: p.max_tokens,
        system: p.system, tools: p.tools};
      const text = JSON.stringify(record);
      if (Buffer.byteLength(text) > 1048576) process.exit(72);
      emit(1, "BENCH_POLICY_CAPTURE_V1 " + text + "\n");
      process.exit(0);
    } catch (_) {
      process.exit(73);
    }
  });
}
