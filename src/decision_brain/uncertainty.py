"""Split, class-conditional conformal sets; no reinforcement-learning claims.

Temperature fitting and conformal quantiles use disjoint calibration rows.
Coverage requires exchangeability; it is not conditional accuracy after abstention.
"""
import math
import numpy as np
from scipy.optimize import minimize_scalar
from decision_brain.network import single_loss


def calibrate(net, x, targets, seed, joint_alpha=0.1):
    if not 0 < joint_alpha < 1 or len(x) < 10:
        raise ValueError('Invalid uncertainty calibration sample or alpha')
    order = np.random.default_rng(seed + 731).permutation(len(x))
    temperature_rows, conformal_rows = np.array_split(order, 2)
    before = net.predict(x[temperature_rows])
    net.temperature = []
    for i, y in enumerate(targets):
        objective = lambda log_t: single_loss(net._raw_prob(x[temperature_rows], i, np.exp(log_t)), y[temperature_rows])
        result = minimize_scalar(objective, bounds=(math.log(.25), math.log(8.)), method='bounded')
        # Retain the neutral temperature when optimization fails or is worse.
        log_t = float(result.x) if result.success and objective(result.x) < objective(0.) else 0.
        net.temperature.append(float(np.exp(log_t)))
    probabilities = net.predict(x[conformal_rows])
    alpha = joint_alpha / len(targets)
    heads = []
    for p, y in zip(probabilities, targets):
        labels = y[conformal_rows]
        quantiles, counts = [], []
        for k in range(p.shape[1]):
            scores = 1. - p[labels == k, k]
            n = len(scores)
            rank = math.ceil((n + 1) * (1 - alpha))
            # The score is bounded by 1. Missing/rare classes stay in every set.
            q = 1. if rank > n else float(np.sort(scores)[rank - 1])
            quantiles.append(q); counts.append(n)
        heads.append({'quantiles': quantiles, 'class_counts': counts})
    policy = {'method': 'class_conditional_split_conformal_v1', 'joint_alpha': joint_alpha,
              'head_alpha': alpha, 'temperature_rows': len(temperature_rows),
              'conformal_rows': len(conformal_rows), 'heads': heads}
    validate_policy(policy, net.counts)
    audit = {'partition_seed': seed + 731, 'temperature_indices': temperature_rows.tolist(),
             'conformal_indices': conformal_rows.tolist(),
             'temperature_fit_loss_before': [single_loss(p, y[temperature_rows]) for p, y in zip(before, targets)],
             'temperature_fit_loss_after': [single_loss(p, y[temperature_rows]) for p, y in zip(net.predict(x[temperature_rows]), targets)],
             'selection_uses_test': False}
    return policy, audit


def validate_policy(policy, counts):
    if policy is None:
        return
    if not isinstance(policy, dict) or policy.get('method') != 'class_conditional_split_conformal_v1':
        raise ValueError('Unknown uncertainty policy')
    alpha = policy.get('joint_alpha')
    if type(alpha) not in (int, float) or not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError('Invalid uncertainty alpha')
    if len(policy.get('heads', [])) != len(counts):
        raise ValueError('Invalid uncertainty heads')
    if not math.isclose(policy.get('head_alpha', -1), alpha / len(counts)):
        raise ValueError('Invalid per-head alpha')
    for key in ('temperature_rows', 'conformal_rows'):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise ValueError('Invalid calibration counts')
    for head, k in zip(policy['heads'], counts):
        q, n = head.get('quantiles', []), head.get('class_counts', [])
        if len(q) != k or len(n) != k:
            raise ValueError('Invalid uncertainty class sizes')
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in q):
            raise ValueError('Invalid conformal quantiles')
        if any(type(v) is not int or v < 0 for v in n) or sum(n) != policy['conformal_rows']:
            raise ValueError('Invalid conformal sample counts')
        if any(math.ceil((v + 1) * (1 - policy['head_alpha'])) > v and q[i] != 1. for i, v in enumerate(n)):
            raise ValueError('Rare classes require conservative quantiles')


def prediction_set(probabilities, head):
    return np.flatnonzero(1. - np.asarray(probabilities, dtype=np.float64) <= np.asarray(head['quantiles']) + 1e-7).tolist()


def diagnostics(spec, probabilities, targets, policy, selection_scores=None):
    from decision_brain.brain import judge
    old, new = [], []
    for i in range(len(targets[0])):
        p = [v[i] for v in probabilities]
        old.append(judge(spec, p)); new.append(judge(spec, p, policy, None if selection_scores is None else [None if v is None else float(v[i]) for v in selection_scores]))
    correct = np.logical_and.reduce([p.argmax(1) == y for p, y in zip(probabilities, targets)])
    result = {}
    for name, rows in [('fixed_threshold', old), ('conformal_policy', new)]:
        automatic = np.array([not any(a['needs_review'] for a in r['answers'].values()) for r in rows])
        result[name] = {'cases': len(rows), 'automated': int(automatic.sum()),
                        'coverage': float(automatic.mean()), 'review_rate': float(1 - automatic.mean()),
                        'automated_errors': int((automatic & ~correct).sum()),
                        'selective_accuracy': float(correct[automatic].mean()) if automatic.any() else None}
    result['heads'] = {}
    all_covered = []
    for d, p, y, h in zip(spec['decisions'], probabilities, targets, policy['heads']):
        sets = [prediction_set(row, h) for row in p]
        covered = np.array([int(label) in choices for label, choices in zip(y, sets)])
        all_covered.append(covered)
        result['heads'][d['id']] = {'set_coverage': float(covered.mean()),
                                   'mean_set_size': float(np.mean([len(s) for s in sets])),
                                   'empty_sets': sum(not s for s in sets),
                                   'per_class_coverage': {o['id']: float(covered[y == k].mean()) if (y == k).any() else None for k, o in enumerate(d['options'])}}
    result['joint_set_coverage'] = float(np.logical_and.reduce(all_covered).mean())
    result['limitations'] = 'Synthetic test coverage is not real-world reliability. Exchangeability is required; OOD and contradictions may remain confidently wrong. Set coverage is not selective accuracy.'
    return result


def quality_gate(summary, policy):
    """Empirical release check, distinct from the theoretical nominal guarantee."""
    errors = []
    coverage = summary.get('joint_set_coverage')
    target = 1 - policy['joint_alpha']
    if type(coverage) not in (int, float) or not math.isfinite(coverage) or not target <= coverage <= 1:
        errors.append('uncertainty: joint_set_coverage_below_nominal_target')
    if summary.get('conformal_policy', {}).get('automated', 0) <= 0:
        errors.append('uncertainty: no_automated_cases_to_validate')
    return errors
