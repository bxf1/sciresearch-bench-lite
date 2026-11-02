"""Select nine frozen group results, retaining the cost of every research session."""
import copy
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runner.common import read_json, write_json, file_hash
from tools.analyze_optimized_r1 import (checkpoint_samples, numeric_samples, numeric_summary,
    resources, timing, model_request_audit, PROFILES)

OLD = ROOT / 'results/optimized-r1-20261101'
EXTRA = ROOT / 'results/optimized-r1-supplement-20261101'
OUT = ROOT / 'results/r1-complete-20261101'


def ref(path):
    return {'path': str(path.relative_to(ROOT)), 'sha256': file_hash(path)}


def main():
    OUT.mkdir(exist_ok=True)
    a = copy.deepcopy(read_json(OLD / 'analysis.json'))
    raw = copy.deepcopy(read_json(OLD / 'results.json'))
    extra = read_json(EXTRA / 'analysis.json')
    assert extra['status'] == 'passed'
    plan = read_json(ROOT / 'freezes/research-run-plan-optimized-r1-supplement-20261101.json')
    entry, = read_json(ROOT / 'research-runs' / plan['plan_id'] / 'manifest.json')['attempts']
    run = next(r for r in plan['runs'] if r['group'] == 'g1')
    host = read_json(ROOT / entry['result']['path'])
    root = (ROOT / entry['registry']['path']).parent.parent
    tl = read_json(EXTRA / 'exploration-timeline.json')
    summary = copy.deepcopy(tl['summary'])
    summary['received_public_evaluation_requests'] = sum(
        read_json(p).get('request', {}).get('operation') == 'evaluate'
        for p in (root / 'file-bridge/requests').glob('*.json') if not p.name.endswith('.delivery.json'))
    attempt = {'run_id': run['run_id'], 'attempt_id': entry['attempt_id'], 'parent_attempt': None,
        'status': host['attempt_status'], 'host_wall_seconds': extra['ode']['attempt_wall_seconds'],
        'research_wall_seconds': extra['ode']['research_seconds'], 'registry_root': str(root.relative_to(ROOT)),
        'host': entry['result'], 'summary': summary, 'model_request_audit': model_request_audit(root)}
    a['attempts'].append(attempt)
    ode = next(r for r in raw['rows'] if (r['run']['task'], r['run']['group']) == ('ode', 'g1'))
    old_ode = next(r for r in a['rows'] if (r['task'], r['group']) == ('ode', 'g1'))
    old_run_id = old_ode['run_id']
    ode.update(run=run, attempt=entry, host_status=host['attempt_status'], main=read_json(EXTRA / 'ode/main-result.json'))
    diag = read_json(EXTRA / 'ode/diagnostic-result.json')
    ode['diagnostic'] = {'status': diag['status'], 'profiles': {'diagnostic-test/all/forward': diag['result']}}
    old_ode.update(run_id=run['run_id'], attempt_id=entry['attempt_id'], host_status=host['attempt_status'],
        attempt_count=2, exploration=summary, research_wall_seconds=attempt['research_wall_seconds'])
    for target, key in [('all_attempt_known_output_tokens', 'known_output_tokens'),
                        ('all_attempt_charged_output_tokens', 'charged_output_tokens')]:
        old_ode[target] += summary[key]
    old_ode['all_attempt_host_wall_seconds'] += attempt['host_wall_seconds']
    old_ode['all_attempt_research_wall_seconds'] += attempt['research_wall_seconds']
    p = next(r for r in raw['rows'] if (r['run']['task'], r['run']['group']) == ('poisson', 'g2'))
    value = read_json(EXTRA / 'poisson/result.json')['result']
    prior_checkpoint = p['main']['diagnostics']['first']
    checkpoint = {'checkpoint_id': prior_checkpoint['checkpoint_id'], 'source_hash': prior_checkpoint['source_hash'],
        'repeats': [value], 'replay_count': 1, 'evaluation_status': value['evaluation_status'],
        'score': value['score'], 'reward': value['reward']}
    p['main'] = {'scope': 'derived_report_view', 'source': ref(EXTRA / 'poisson/result.json'),
        'diagnostics': {'evaluation_status': 'valid', 'score': value['score'], 'reward': value['reward'],
            'selection_reason': 'explicit_finalize', 'first': checkpoint,
            'final': {**checkpoint, 'replay_count': 0, 'reused_from': checkpoint['checkpoint_id']}}}
    cases = []
    for row in a['rows']:
        item = next(r for r in raw['rows'] if (r['run']['task'], r['run']['group']) == (row['task'], row['group']))
        task, run_id = row['task'], row['run_id']
        d = item['main']['diagnostics']
        row.update(evaluation_status=d['evaluation_status'], first_score=d['first']['score'], final_score=d['score'],
            reward=d['reward'], first=d['first'], final=d['final'], selection_reason=d['selection_reason'], reason=None)
        for role in ('first', 'final'):
            record = d[role]; samples = checkpoint_samples(record)
            row['main_numeric'][role] = {'overall': numeric_summary(samples, task, 12),
                'numeric_origin': 'frozen_candidate_replay',
                'by_level': {str(level): numeric_summary(samples, task, 4, level=level) for level in range(3)},
                'resources': resources(samples), 'timing': timing(record['repeats'][0]) if task == 'poisson' else None,
                'reused_from': record.get('reused_from')}
            for i, sample in enumerate(samples, 1):
                cases.extend({'run_id': run_id, 'task': task, 'group': row['group'], 'split': 'final-test',
                    'role': role, 'order': 'forward', 'replay': i, **r} for r in sample.get('cases', []))
        diagnostic = item['diagnostic']; row['diagnostic_status'] = diagnostic['status']
        for profile in PROFILES[task]:
            for direction in (('forward', 'reverse') if profile == 'cache_order' else ('forward',)):
                result = diagnostic['profiles'][f'diagnostic-test/{profile if task == "poisson" else "all"}/{direction}']
                samples = numeric_samples(result)
                row['diagnostics'][profile + '/' + direction] = {'numeric': numeric_summary(samples, task, 4, profile=profile),
                    'resources': resources(samples), 'resource_scope': 'theme_batch' if task == 'poisson' else 'all_12_diagnostic_cases',
                    'timing': timing(result) if task == 'poisson' else None, 'evaluation_status': result['evaluation_status']}
                for i, sample in enumerate(samples, 1):
                    cases.extend({'run_id': run_id, 'task': task, 'group': row['group'], 'split': 'diagnostic-test',
                        'role': 'final', 'order': direction, 'replay': i, **r} for r in sample.get('cases', []) if r.get('profile_id') == profile)
    a.update(scope='nine_group_complete_results', reported_groups=9, scientific_sessions=10,
        hidden_scoring_after_all_nine_closed=None, research_closed_at=None, first_hidden_scoring_at=None,
        closure_policy='Each selected candidate was sealed before its own private scoring. Do not infer a single global closure time for all ten sessions.',
        selection_policy='One final result per group; ODE G1 uses its latest independent sealed research. All ten research sessions remain in cost accounting. Poisson G2 uses the accepted fixed-source timing record.',
        original_ode_run_id=old_run_id, case_observation_count=len(cases))
    a.pop('accuracy_only_supplement', None)
    a['interpretation'] = 'Nine configurations are represented by nine selected candidate results; ten scientific sessions were executed. Numerical replays are not independent Agent samples. No cross-group significance claim.'
    totals = a['totals']
    totals.update(attempts=10, valid_main_results=9, reward_one=9, registered_final_candidates=9)
    for target, key in [('known_output_tokens_all_attempts', 'known_output_tokens'), ('charged_output_tokens_all_attempts', 'charged_output_tokens')]:
        totals[target] = sum(x['summary'][key] for x in a['attempts'])
    for target, key in [('research_wall_seconds_all_attempts', 'research_wall_seconds'), ('host_wall_seconds_all_attempts', 'host_wall_seconds')]:
        totals[target] = sum(x[key] for x in a['attempts'])
    a['source_evidence'] += [ref(EXTRA / name) for name in ('analysis.json', 'ode/main-result.json', 'ode/diagnostic-result.json',
        'poisson/result.json', 'exploration-timeline.json', 'sensitivity-audit.json')]
    a['source_evidence'] += [ref(OLD / 'analysis.json'), entry['result'], entry['registry']]
    for evidence in a['source_evidence']:
        assert file_hash(ROOT / evidence['path']) == evidence['sha256']
    raw.update(scope=a['scope'], reported_groups=9, scientific_sessions=10, status='selected_results_complete',
               source_results=[ref(OLD / 'results.json'), ref(EXTRA / 'results.json')])
    write_json(OUT / 'results.json', raw); write_json(OUT / 'analysis.json', a)
    write_json(OUT / 'case-results.json', cases)
    keys = sorted({k for row in cases for k in row})
    with (OUT / 'case-results.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=keys); writer.writeheader()
        for row in cases:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    timeline = copy.deepcopy(read_json(OLD / 'exploration-timeline.json'))
    timeline.update(scientific_sessions=10, reported_groups=9)
    timeline['attempts'].append({'run_id': run['run_id'], 'attempt_id': entry['attempt_id'], 'parent_attempt': None,
        'attempt_status': host['attempt_status'], **{k: v for k, v in tl.items() if k not in ('scientific_sessions', 'run_id')}})
    write_json(OUT / 'exploration-timeline.json', timeline)
    notes = copy.deepcopy(read_json(OLD / 'method-analysis.json'))
    m = next(m for m in notes['methods'] if m['run_id'] == old_run_id)
    m.update(run_id=run['run_id'], title='平滑稀疏回归、多支撑选择与轨迹拟合',
        method='先用 Savitzky-Golay 平滑求导（31 点窗口、三次多项式）和序贯阈值最小二乘形成基线，联合使用公开 train 与 validation 轨迹。最终版本增加多阈值、显著性筛选和穷举子集 BIC 支撑提议，在最多 10 个非零系数约束下尝试 DOP853 灵敏度积分与加权轨迹残差拟合；数值异常时回退到平滑稀疏回归。',
        exploration='先检查六例开发数据，修正本地脚本的维度与返回值错误，再用自建合成轨迹比较支撑筛选和轨迹拟合。还进行了高噪声、边界系统及 12 例批处理规模试验。第 8.02、13.17、17.40 分钟分别登记三个独立源码版本，共 41 条可见 shell 命令、3 次公开评估、38 次成功模型请求。',
        changes='由快速平滑回归扩展到多支撑候选，调整 BIC 候选池，并为最终实现加入 95 秒软预算和异常回退。18.38 分钟时明确提交 candidate-003，主测试首次至最终提高 0.226 分；主测试执行时间中位数从 0.464 秒增至 34.785 秒。资源开销增加远大于此次精度分的改善。',
        limitations='合成有限差分检查发现灵敏度列序与 C.ravel() 的交错系数顺序不一致，相对差异为 1.103；正确重排列后降至 6.47e-11。此项仅为实现诊断，没有修改封存代码或重算成绩，不能单独解释实际得分。95 秒软预算只在支撑循环边界检查，不能保证中途积分及时退出。主任务和三个结构主题均通过，仍不能据此证明任意系统上的适用性。',
        evidence=[ref(root / 'registry/snapshots/candidate-003/solve.py'), ref(root / 'registry/state.json'),
                  ref(root / 'auxiliary-agent/pi.txt'), ref(EXTRA / 'sensitivity-audit.json')])
    notes['failure_analysis'] = '''**Heat 的诊断失败发生在初场恢复质量上。** 三组均在谱衰减指数为 1 的中、高难度两例上未通过初场误差门槛，主题最大初场误差约 0.321-0.327，但未来场最大误差仍低于 0.004。扩散后的良好拟合可能掩盖高频恢复不足。指数为 3 的两例、幅度和连续缺失主题均通过。

**实现检查与科学通过分别解释。** ODE G1 虽通过全部主测试和诊断，灵敏度列序检查仍发现缺陷，且最终候选只获得有限分数收益。通过有限样本不能替代实现正确性检查；没有将实现风险擅自改判为科学失败。

**计时使用合格观测。** Poisson 三组正式结果均来自满足冻结条件的 BCCBBC 记录。拒绝窗口和请求层失败保留在执行证据中；所有有效窗口均有完整宿主观测覆盖，不选择最快重放。'''
    notes['conclusions'] = f'''**交付能力。** 九组配置均有封存的可执行候选，首次合法登记约 3.63-26.02 分钟。全部 10 个研究会话实际占用 {totals['research_wall_seconds_all_attempts']/60:.2f} 分钟，宿主 attempt 墙钟合计 {totals['host_wall_seconds_all_attempts']/60:.2f} 分钟；后一指标包含启动与收尾，不含后续评分等待。已知输出 {totals['known_output_tokens_all_attempts']:,} token，预算计入 {totals['charged_output_tokens_all_attempts']:,} token；预算计入量不等于服务商账单。

**科学质量。** 九个最终候选主测试均三次 12/12 通过，九组 reward 均为 1。Heat 分数为 91.543、83.506、91.016；ODE 为 96.863、98.939、98.488；Poisson 正式加速比分别为 3.900、2.583、3.378 倍。不同任务分数不能合并为统一能力量尺。

**探索收益。** Heat G3 首次至最终提高 0.928 分，ODE G1 提高 0.226 分，Poisson G3 提高 17.310 分。ODE G1 的时间开销明显上升，表明更多复杂拟合未必划算。Poisson G1 下降 0.425 分，不能据此区分算法收益与计时波动；ODE G3 两个不同源码版本的主测试指标相同。公开评估次数不能代表全部探索量。

**适应能力。** Heat 三组诊断均为 10/12，共同边界在慢谱衰减主题。ODE 三组均为 12/12；Poisson 三组均通过各主题及缓存逆序检查。36 对已保存的正逆序缓存输出逐字节相同；这只覆盖本批两个算子及四组 RHS 的排列，不证明任意缓存序列安全。'''
    notes['problems'] = '''### 8.1 交付效率与执行保障

保留自主探索和硬截止，将长命令改为可轮询作业，提供剩余预算状态，并在共同说明中解释长阻塞可能延迟提醒。全部执行记录包含一次 ODE G1 未登记候选的会话；九组结果表对应各组选定的最终候选，不能据此宣称所有启动都在首次研究中交付成功。成本表保留全部会话用量。

选定会话每组登记 1-3 个源码版本，20 次公开评估额度并非主要瓶颈。优先降低本地调试与反馈等待成本，避免先增加评估额度。ODE G1 已提供可运行基线，但复杂拟合增益很小，应结合精度与资源开销决定是否继续迭代。

### 8.2 科学指标与方法边界

Heat 应同时关注可辨识模态、先验敏感性和初场不确定性；观测残差与未来场误差容易遗漏高频偏差。可在统一开发工具中加入合成压力试验，检验幅度与谱先验的适应性。本批没有证明某一种修正必然解决慢谱衰减问题。

ODE 应保留轨迹和向量场双指标，明确 train/validation 都是开发数据。G1 的解析雅可比必须先与有限差分核对；G2 的噪声修正不覆盖所有坐标幂次，G3 的系数取整依据与真实连续分布不符，均需针对性检查。三个方法在本批结构诊断均通过，不能把源码风险直接写成已发生的测试失败。

Poisson 应分开报告完整进程性能与求解阶段解释。G1/G3 减少导入开销，但私有扩展和 ctypes 接口降低依赖可移植性；G2 的标准 SuperLU 接口更直接，网格扩大后的填充与内存仍需评估。启动优化与分解规模效应应分别分析。

### 8.3 计时与实验设计

正式性能测量应使用专用、可控的宿主，保持固定 BCCBBC 顺序、预先声明的尝试上限、首次有效选择和全部拒绝记录。数值正确性与计时资格分开记录，不能把环境无效改写为算法零分或选择最快时刻。

下一版观察器可事先将异常采样间隙纳入拒绝规则，并保存单调时钟与墙钟对照。当前策略禁止新 swap-out，将无法归因的全局 swap-in 作为诊断；候选容器自身禁止 swap，两者须清楚区分。

本报告是九组配置的案例分析。执行次数和候选选择过程并非均衡重复设计，因此不做指导强度的显著性排名。若研究普遍效果，需另行预注册独立会话与随机化区组；增加计时次数和测试实例不能替代独立 Agent 样本。'''
    write_json(OUT / 'method-analysis.json', notes)
    write_json(OUT / 'selection-manifest.json', {'reported_groups': 9, 'scientific_sessions': 10,
        'selection_policy': a['selection_policy'], 'sources': raw['source_results'],
        'selected': [{'label': r['label'], 'run_id': r['run_id'], 'final_source_hash': r['final']['source_hash'],
                      'score': r['final_score'], 'reward': r['reward']} for r in a['rows']]})
    print(json.dumps({'status': 'prepared', 'groups': 9, 'scientific_sessions': 10, **totals}))


if __name__ == '__main__':
    main()
