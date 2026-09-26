"""Human-readable algorithm comparison with validation-only routing evidence."""
import html
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def render_comparison(report,out):
    results=report['algorithm_comparison'];selection=report['router_selection'];names=list(results)
    fig,axes=plt.subplots(1,3,figsize=(15,4));colors=['#64748b','#2563eb','#8b5cf6','#d97706','#059669']
    axes[0].bar(names,[results[n]['test_loss'] for n in names],color=colors,label='Loss media en test')
    axes[0].set(ylabel='Entropía cruzada',title='Error probabilístico — menor es mejor')
    axes[1].bar(names,[100*results[n]['selective']['conformal_policy']['coverage'] for n in names],color=colors,label='Sin revisión en ninguna cabeza')
    axes[1].set(ylabel='Casos (%)',ylim=(0,105),title='Automatización después de gates')
    axes[2].bar(names,[results[n]['selective']['conformal_policy']['automated_errors'] for n in names],color=colors,label='Alguna cabeza incorrecta')
    axes[2].set(ylabel='Casos',title='Errores automatizados',ylim=(0,max(1,max(results[n]['selective']['conformal_policy']['automated_errors'] for n in names)+1)))
    for i,n in enumerate(names):axes[2].text(i,results[n]['selective']['conformal_policy']['automated_errors']+.03,str(results[n]['selective']['conformal_policy']['automated_errors']),ha='center')
    from matplotlib.ticker import MaxNLocator
    axes[2].yaxis.set_major_locator(MaxNLocator(integer=True))
    for ax in axes:ax.tick_params(axis='x',rotation=30);ax.legend(fontsize=8)
    fig.tight_layout();fig.savefig(out/'algorithms.png',dpi=140);plt.close(fig)
    rows=[]
    for name,r in results.items():
        s=r['selective']['conformal_policy'];quality='PASS' if r['autoevals_passed'] and r['uncertainty_passed'] else 'FAIL'
        rows.append(f"<tr><td>{name}</td><td>{r['test_loss']:.5f}</td><td>{r['harness_passed']}/{r['harness_total']}</td><td>{s['automated']}/{s['cases']}</td><td>{s['automated_errors']}</td><td>{r['selective']['joint_set_coverage']:.1%}</td><td>{quality}</td></tr>")
    routing=[]
    for d,head in zip(report['metrics'],selection['heads']):
        losses='; '.join(f"{v['algorithm']}: {v['log_loss']:.4f}" for v in head['candidates'])
        routing.append(f"<tr><td>{html.escape(d)}</td><td>{head['selected']}</td><td>{losses}</td></tr>")
    body='''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Comparación y router</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:30px auto;padding:24px;background:#f5f7fb;color:#172033}table{border-collapse:collapse;background:white;width:100%}td,th{padding:10px;border-bottom:1px solid #d6dfeb;text-align:left}img{width:100%}h1{line-height:1.2}.notice{background:#fff1d7;padding:16px}a{color:#1256a0}</style><h1>Algoritmos de decisión y router</h1><p>Neural: referencia. Ensemble: promedio de tres redes. CORN: probabilidades ordinales condicionales para Score. Selective: adaptación multisalida de SelectiveNet con selector y cabeza auxiliar. Router: selección fija por cabeza.</p><p class="notice">El router se fijó antes de calibrar y evaluar test. Estos resultados no cambian las rutas. Que un candidato gane aquí no autoriza producción ni demuestra superioridad general.</p><h2>Resultado medido</h2><table><tr><th>Algoritmo</th><th>Loss</th><th>Harness</th><th>Automatizados</th><th>Errores automatizados</th><th>Cobertura conjunta de conjuntos</th><th>Calidad</th></tr>'''+''.join(rows)+'''</table><figure><img src="algorithms.png" alt="Comparación de loss, automatización y errores"><figcaption>Un error automatizado cuenta cuando alguna cabeza difiere de su etiqueta. No es pérdida económica ni resultado causal de una acción. La cobertura de conjuntos y la automatización son medidas distintas.</figcaption></figure><h2>Qué algoritmo atiende cada decisión</h2><table><tr><th>Cabeza</th><th>Ruta elegida</th><th>Loss en validación del router, antes de calibrar</th></tr>'''+''.join(routing)+'''</table><p>El router elige por menor loss en la mitad de validación reservada para routing, con los umbrales fijados en config/algorithm_router.json. La otra mitad solo decide cuándo detener entrenamiento. No se comparan probabilidades máximas de distintos modelos para elegir por petición.</p><p>Todos ven las mismas características numéricas y TF-IDF. Estos experimentos no añaden comprensión mediante un encoder semántico preentrenado. El selector aprende aceptación, pero su score no es probabilidad de corrección. La implementación es una adaptación local de los objetivos publicados, no una reproducción de sus benchmarks.</p><p><a href="report.html">Informe general</a> · <a href="comparison.json">Resultados completos y rutas</a></p></html>'''
    (out/'comparison.html').write_text(body,encoding='utf-8')
    path=out/'report.html';text=path.read_text(encoding='utf-8')
    text=text.replace('<h1>', '<p><a href="comparison.html">Abrir comparación de algoritmos y router</a></p><h1>',1)
    text=text.replace('Pérdida del candidato seleccionado', 'Pérdida de la red de referencia')
    text=text.replace('<h2>Aprendizaje y evaluación</h2>', '<h2>Aprendizaje y evaluación</h2><p>Las curvas por época corresponden a la red de referencia. El router combina cabezas seleccionadas y no tiene una curva de entrenamiento única.</p>')
    path.write_text(text,encoding='utf-8')
