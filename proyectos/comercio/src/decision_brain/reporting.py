"""Spanish reports, chart legends and user-facing interpretation."""
import html
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def render(report,out):
    esc=html.escape
    candidate=report['search'][report['selected_trial']]
    h=candidate['epochs']
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(8,4))
    ax.plot([v['epoch'] for v in h],[v['train_loss'] for v in h],label='Entrenamiento',color='#2563eb')
    ax.plot([v['epoch'] for v in h],[v['validation_loss'] for v in h],label='Validación',color='#d97706')
    ax.set(xlabel='Época',ylabel='Entropía cruzada media',title='Pérdida del candidato seleccionado, antes de calibrar')
    ax.legend(title='Partición');ax.grid(alpha=.2);fig.tight_layout();fig.savefig(out/'loss.png',dpi=150);plt.close(fig)
    rows=[];images=[]
    for name,m in report['metrics'].items():
        cm=np.asarray(m['confusion_matrix']);fig,ax=plt.subplots(figsize=(7,5))
        im=ax.imshow(cm,cmap='Blues',vmin=0)
        ax.set(xticks=range(len(m['labels'])),yticks=range(len(m['labels'])),
               xlabel='Clase predicha',ylabel='Clase real',title=name)
        ax.set_xticklabels(m['labels'],rotation=30,ha='right');ax.set_yticklabels(m['labels'])
        for i in range(len(cm)):
            for j in range(len(cm)):
                ax.text(j,i,str(cm[i,j]),ha='center',va='center',color='white' if cm[i,j]>.5*cm.max() else 'black')
        fig.colorbar(im,ax=ax,label='Número de casos');fig.tight_layout()
        file=f'confusion_{name}.png';fig.savefig(out/file,dpi=150,bbox_inches='tight');plt.close(fig)
        images.append(f'<figure><img src="{file}" alt="Matriz {esc(name)}"><figcaption>Filas: etiquetas reales. Columnas: predicciones. Las celdas fuera de la diagonal son errores.</figcaption></figure>')
        gain=100*(m['accuracy']-m['baseline_accuracy'])
        rows.append(f'<tr><td>{esc(m["question"])}</td><td>{m["accuracy"]:.1%}</td><td>{m["baseline_accuracy"]:.1%}</td><td>{gain:+.1f} pp</td><td>{m["log_loss"]:.4g}</td></tr>')
    names=list(report['metrics']);fig,ax=plt.subplots(figsize=(max(7,len(names)*1.5),4))
    x=np.arange(len(names));width=.36
    ax.bar(x-width/2,[100*report['metrics'][n]['accuracy'] for n in names],width,label='Modelo')
    ax.bar(x+width/2,[100*report['metrics'][n]['baseline_accuracy'] for n in names],width,label='Clase mayoritaria de entrenamiento')
    ax.set(xticks=x,xticklabels=names,ylim=(0,105),ylabel='Exactitud (%)',title='Resultado en prueba frente a referencia')
    ax.tick_params(axis='x',rotation=20);ax.legend();fig.tight_layout();fig.savefig(out/'accuracy.png',dpi=150);plt.close(fig)
    examples=[]
    for entry in report['scenarios']:
        fields=''.join(f'<dt>{esc(k)}</dt><dd>{esc(str(v))}</dd>' for k,v in entry['state'].items())
        examples.append(f'<article><dl>{fields}</dl><p>{esc(entry["interpretation"])}</p><p><strong>Acción propuesta: {esc(entry["proposed_action"])}</strong></p><p>{esc(entry["routing_reason"])}</p></article>')
    warning=('Estos datos proceden del generador sintético. Se reservan expresiones diferentes por partición, pero comparten las reglas del generador. No acreditan rendimiento en una industria real.' if report['data_origin']=='synthetic_demo' else 'La validez depende de cómo se separaron los datos suministrados. Mantenga organizaciones, autores o períodos relacionados en una sola partición.')
    text=f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Informe de decisiones</title>
<style>body{{font:16px system-ui;max-width:1080px;margin:40px auto;padding:0 22px;color:#172033;background:#f7f9fc}}h1,h2{{line-height:1.2}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;border-bottom:1px solid #dbe1ea;text-align:left}}img{{width:100%;max-width:850px}}article{{background:white;padding:20px;margin:20px 0;border-radius:10px}}dt{{font-weight:600}}dd{{margin:0 0 10px}}figcaption,.note{{color:#526078}}figure{{margin:24px 0}}</style>
<h1>Cerebro de decisiones: {esc(report['industry'])}</h1><p>Prueba con {report['split_sizes']['test']} casos. Pérdida media después de calibrar: <strong>{report['test_loss']:.5g}</strong>.</p>
<p>{esc(warning)}</p><p>La prueba funcional confirma que el modelo guardado conserva sus predicciones al recargarlo. La exactitud indica cuántas etiquetas coincide con los datos; no prueba que las acciones causen un resultado favorable.</p>
<table><tr><th>Pregunta</th><th>Exactitud</th><th>Referencia</th><th>Diferencia</th><th>Loss</th></tr>{''.join(rows)}</table>
<h2>Aprendizaje y evaluación</h2><figure><img src="loss.png"><figcaption>Una pérdida menor representa más probabilidad asignada a las etiquetas correctas. Una brecha creciente entre entrenamiento y validación puede indicar sobreajuste.</figcaption></figure><figure><img src="accuracy.png"><figcaption>La referencia predice la clase más frecuente observada en entrenamiento. Ganarle es una comparación inicial, no una validación de producción.</figcaption></figure>{''.join(images)}
<h2>Interpretación en escenarios</h2><p>Las acciones se proponen para el flujo de trabajo; no se ejecutan. Los criterios y preguntas proceden del contrato y no son explicaciones causales aprendidas.</p>{''.join(examples)}</html>'''
    (out/'report.html').write_text(text,encoding='utf-8')
