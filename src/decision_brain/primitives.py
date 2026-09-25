"""Local question semantics; no external model or proprietary confidence formula."""
import math


def question_type(decision):
    return 'noul' if decision['kind'] == 'boolean' else decision['kind']


def distribution_confidence(probabilities):
    """1 - normalized Shannon entropy. Not a probability of being correct."""
    p = list(probabilities)
    total = sum(p)
    entropy = -sum((v / total) * math.log(v / total) for v in p if v > 0)
    return max(0.0, min(1.0, 1.0 - entropy / math.log(len(p))))


def result_fields(decision, probabilities):
    kind = question_type(decision)
    result = {'type': kind}
    if kind == 'noul':
        result['noul'] = float(probabilities['true'])
    else:
        result['confidence'] = distribution_confidence(probabilities.values())
        if kind == 'score':
            result['score'] = sum(i * probabilities[o['id']] for i, o in enumerate(decision['options']))
            result['legend'] = {o['id']: {'level': i, 'description': o['meaning']} for i, o in enumerate(decision['options'])}
    return result


def describe_answer(answer):
    prefix = 'Requiere revisión. ' if answer['needs_review'] else ''
    if answer['type'] == 'noul':
        detail = f"Probabilidad de que la afirmación sea verdadera: {answer['noul']:.1%}. Cerca de 0,5 indica ambigüedad, no intensidad."
    elif answer['type'] == 'score':
        top = len(answer['probabilities']) - 1
        detail = f"Posición en la rúbrica: {answer['score']:.3f} de {top}; confianza de distribución: {answer['confidence']:.1%}."
    else:
        detail = f"{answer['meaning']}. Probabilidad de la opción: {answer['max_probability']:.1%}; confianza de distribución: {answer['confidence']:.1%}."
    return f"{answer['question']} {prefix}{detail}"
