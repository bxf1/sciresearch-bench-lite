# Native Harbor Trial and bounded model relay pilot

This is a local functional result, not a formal G1/G2/G3 study. The full native
Harbor `Trial.create → SingleStepTrial → Pi → separate verifier` lifecycle ran
with the pinned Pi 0.84.1 and Harbor commit
`38b9be0164a910015a0be9a37ba6e8e78c562dfe`; no Harbor source was modified.

最新[harbor-native-pilot-002](../logs/harbor-native-pilot-002/result.json)再次完成完整生命周期，使用新版worker和每请求系统/工具哈希门禁。8次上游请求全部成功，输出2,413 tokens；显式finalize的候选hash为 `3731135f6a9a91405e0b5b6d5c7af543c97a9296f0b57e7dfc185492bf39db9e`，三次pilot重放各3/3通过，score=89.30228457567675、reward=1。first/final相同，没有迭代收益；native异常为空、relay额度结清且资源清理无错。以下保留第一轮的独立记录。

[harbor-native-pilot-001](../logs/harbor-native-pilot-001/result.json) completed
successfully. Research used only the six heat public-dev cases, 600 seconds,
four accepted evaluation slots, twelve model turns, and R limits of 1 CPU and
1 GiB. It registered and explicitly finalized one valid candidate,
`174e4e6eb1d349a28504c53c5e578b087388e66dc597d597213457509b410c50`.
Three independent W/J replays each passed all three pilot-smoke cases; mean
score was 89.30228457567655 and reward was 1. First and final are the same
candidate, so final reused those replays. No iteration benefit or final-test
result is established.

The dedicated relay made nine upstream requests, all HTTP 200 and successful.
Its trusted complete usage records total 7,854 uncached input tokens, 55,552
cache-read input tokens, zero cache-creation tokens and 2,694 output tokens.
Cost remains null. Pi requested 16,384 output tokens per request; the relay
clamped each request to 4,096 and enforced an aggregate session output budget
of 32,768. All reservations were settled, no requests remained active and no
protocol/evidence failure was recorded. Total controller wall time, including
setup and verification, was approximately 131.82 seconds.

The relay fixes the HTTPS upstream and model, writes `thinking={type:disabled}`,
`temperature=0.0` and `top_p=1.0` into the actual upstream body, and records body,
system and tool hashes without retaining request bodies. Its strict stream
parser rejects thinking blocks, inconsistent/decreasing usage and incomplete
terminal streams. Failure or unknown usage consumes the full reservation.
The pilot passed this parser; auxiliary Pi logs also observed zero thinking
blocks. This proves the submitted request policy and accepted stream shape,
not an undisclosed provider-side model revision or internal implementation.

The provider credential stayed in the dedicated relay. R received only a new,
short-lived relay token; retained records redact that token. W/J received no
model credential. The host kept the registry and source snapshots outside R.
Automatic native trajectory/artifact download was suppressed; bounded R logs
were retained separately as untrusted auxiliary evidence. The host used native
Harbor lifecycle hooks and its verifier factory, while the independent numeric
W/J implementation owned the scientific verdict.

[Network probe 002](../logs/relay-transport-probe-002/result.json) and the pilot's
own admission probe reached only the admitted relay IP/port. Direct provider,
external IP, spoofed Host and raw TCP attempts failed. Docker DNS at 127.0.0.11
was blocked on TCP/UDP port 53 and the actual random listener ports. The nft
rules apply before native proxy DNAT, including the proxy's own upstream
connections. Probe 001 preceded the DNS repair and is retained with that
limited scope. Neither standalone network probe made a model request.

The pilot verified empty resource lists for both native Harbor sessions and
removed its own relay container/network. Existing user services were not
stopped. [Host termination](../logs/harbor-native-pilot-001/host-termination.json),
[relay events](../logs/harbor-native-pilot-001/relay-evidence/evidence/events.jsonl),
[source snapshot](../logs/harbor-native-pilot-001/controller_snapshot/runner/harbor_pilot.py),
and [derived request rows](../results/runs/harbor-native-pilot-requests.csv)
retain the evidence. The protocol regression suite covers concurrency,
conservative charging, EOF/usage rules and deadline failures; synthetic tests
are not represented as additional live API experiments.

Formal resources remain unchanged at R 4 vCPU/4 GiB and 1800 seconds/20
evaluations. The local daemon has only 2 vCPU and about 3.81 GiB with existing
services. Formal study count remains zero; T3 formal timing/profile and all
final-test solver scores remain pending. This successful pilot does not waive
those gates or replace the remaining execution-plan work.

新版可信进程计时器落地后，已在[统一检查点重放](../logs/checkpoint-worker-replay-local-001/result.json)中重跑三个历史真实模型候选，每个三次：零解均0分，research-loop-pilot-001均87.69277970613776分，harbor-native-pilot-001均89.30228457567655分。各次结果与旧版相同；使用的仍是pilot-smoke，未访问final-test。原研究、旧执行结果和失败attempt均保留，没有把新worker的计时证据写回旧日志。

正式模式不安装12轮扩展，其系统提示hash与pilot不同。[三任务离线捕获](../logs/model-policy-capture-local-001/verification.json)使用原生Pi setup安装的相同版本/源码，在network none中于真正HTTP发送前捕获并同步退出：三任务system hash均为 `77b9bf237a01f9bc8581e44920b2d82878f2fa1dcaa1f14628f737e428d168bd`，tools hash均为 `99653ba38839a24430523861d5b974d2ccc9a68e1506a3aa0394880caa2c515a`。完整system/tools JSON在对应task目录；捕获没有模型调用，不能把pilot系统hash代入正式配置。
