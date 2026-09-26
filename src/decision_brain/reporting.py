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
    rows=[];images=[];typed_rows=[];head_images=[]
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
        if 'type' in m:
            extra=(f"MAE de score: {m['score_mae']:.4f}; RMSE: {m['score_rmse']:.4f}; MAE referencia: {m['baseline_score_mae']:.4f}" if m['type']=='score' else
                   'Brier binario: error cuadrático de la probabilidad de verdadero.' if m['type']=='noul' else 'Brier multiclase: suma de errores cuadráticos por caso.')
            typed_rows.append(f'<tr><td>{esc(name)}</td><td>{esc(m["type"])}</td><td>{esc(m["loss_name"])}: {m["log_loss"]:.5f}</td><td>{m["brier"]:.5f}</td><td>{extra}</td></tr>')
        if h and 'train_head_loss' in h[0]:
            fig,ax=plt.subplots(figsize=(8,4))
            for key,label in [('train_head_loss','Entrenamiento'),('validation_head_loss','Validación')]:
                ax.plot([e['epoch'] for e in h],[e[key][name] for e in h],label=label)
            ax.set(xlabel='Época',ylabel='Entropía cruzada',title=f"{name} — {m['type']}")
            ax.legend(title='Partición');ax.grid(alpha=.2);fig.tight_layout()
            loss_file=f'loss_{name}.png';fig.savefig(out/loss_file,dpi=150);plt.close(fig)
            head_images.append(f'<figure><img src="{loss_file}" alt="Loss de {esc(name)}"><figcaption>Pérdida de {esc(name)} por época, antes de calibrar.</figcaption></figure>')
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
        answer_rows=[]
        for name,a in entry['answers'].items():
            value=a.get('noul',a.get('score',a['choice']))
            confidence=f"{a['confidence']:.1%}" if 'confidence' in a else 'Integrada en noul'
            distribution='; '.join(f'{key}: {prob:.1%}' for key,prob in a['probabilities'].items())
            answer_rows.append(f'<tr><td>{esc(name)}</td><td>{esc(a.get("type",a["kind"]))}</td><td>{esc(str(value))}</td><td>{confidence}</td><td>{esc(distribution)}</td></tr>')
        answer_table='<table><tr><th>Pregunta</th><th>Tipo</th><th>Resultado</th><th>Confianza</th><th>Probabilidades</th></tr>'+''.join(answer_rows)+'</table>'
        examples.append(f'<article>{answer_table}<dl>{fields}</dl><p>{esc(entry["interpretation"])}</p><p><strong>Acción propuesta: {esc(entry["proposed_action"])}</strong></p><p>{esc(entry["routing_reason"])}</p></article>')
    assurance_html=''
    if report.get('assurance'):
        a=report['assurance'];rows_a=[]
        for name,scores in a['scores']['heads'].items():
            ordinal=f"{scores['score_closeness']:.3f}" if 'score_closeness' in scores else 'No aplica'
            rows_a.append(f'<tr><td>{esc(name)}</td><td>{scores["exact_match"]:.1%}</td><td>{scores["probability_quality"]:.3f}</td><td>{ordinal}</td></tr>')
        state='PASS' if a['passed'] else 'FAIL'
        assurance_html=f'<h2>AutoEvals: {state}</h2><p>Evaluación local con AutoEvals {esc(a["version"])}. ExactMatch es el evaluador de la librería; BrierQuality y OrdinalCloseness son scores propios. Sin juez remoto ni envío a Braintrust.</p><table><tr><th>Pregunta</th><th>ExactMatch</th><th>BrierQuality</th><th>OrdinalCloseness</th></tr>{"".join(rows_a)}</table><p>{esc("; ".join(a["reasons"]) or "Cumple los umbrales numéricos. El harness de decisiones debe aprobar por separado.")}</p><p><a href="autoevals.json">Scores por caso</a> · <a href="research/research.json">Registro de investigación</a> · <a href="research/results.tsv">Experimentos TSV</a></p>'
        experiments=report['search'];complete=[e for e in experiments if 'validation_loss' in e]
        fig,ax=plt.subplots(figsize=(8,4))
        ax.errorbar([e['trial'] for e in complete],[e['validation_loss'] for e in complete],yerr=[e.get('validation_loss_std',0) for e in complete],fmt='o-',capsize=4,label='Media ± desviación entre semillas')
        for e in complete:ax.annotate(e.get('status','keep' if e['accepted'] else 'discard'),(e['trial'],e['validation_loss']),xytext=(0,10),textcoords='offset points',ha='center')
        ax.set(xlabel='Experimento',ylabel='Loss de validación',title='Autoresearch: selección sin consultar test');ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(out/'research.png',dpi=150);plt.close(fig)
        experiment_rows=''.join(f'<tr><td>{e["trial"]}</td><td>{esc(e.get("hypothesis",""))}</td><td>{esc(e.get("status",""))}</td><td>{esc("; ".join(e.get("reasons",[])))}</td></tr>' for e in experiments)
        assurance_html+='<figure><img src="research.png" alt="Loss de validación de los experimentos"><figcaption>Las barras son desviación entre semillas, no intervalos de confianza. Keep acepta una configuración para continuar investigando; no autoriza producción.</figcaption></figure><table><tr><th>Experimento</th><th>Hipótesis</th><th>Estado</th><th>Motivo</th></tr>'+experiment_rows+'</table>'
    audit_html=''
    if report.get('dataset_audit'):
        audit=report['dataset_audit']
        audit_rows=''.join(f'<tr><td>{esc(split)}</td><td>{data["rows"]}</td><td>{data["unique_task_texts"]}</td><td>{data["target_combinations"]}</td></tr>' for split,data in audit['splits'].items())
        alerts='; '.join(audit['warnings']) or 'Sin alertas en estas comprobaciones estructurales.'
        audit_html=f'<h2>Diversidad y separación de datos</h2><table><tr><th>Partición</th><th>Filas</th><th>Textos de tarea distintos</th><th>Combinaciones de etiquetas</th></tr>{audit_rows}</table><p>{esc(alerts)}</p><p>Textos idénticos entre particiones: {sum(audit["task_text_overlap"].values())}. Combinaciones globales: {audit["target_combinations"]}. Contar textos y medir asociación de etiquetas no acredita cobertura de casos reales.</p>'
        ablation_rows=[]
        for name,m in report['metrics'].items():
            no_text=report.get('input_ablation',{}).get('without_text',{}).get(name,{})
            no_number=report.get('input_ablation',{}).get('without_numeric',{}).get(name,{})
            ablation_rows.append(f'<tr><td>{esc(name)}</td><td>{m["accuracy"]:.1%}</td><td>{no_text.get("accuracy",0):.1%}</td><td>{no_number.get("accuracy",0):.1%}</td></tr>')
        audit_html+='<h2>Dependencia del texto y los números</h2><table><tr><th>Pregunta</th><th>Modelo completo</th><th>Sin texto</th><th>Sin números</th></tr>'+''.join(ablation_rows)+'</table><p>Se anulan bloques de características del mismo modelo; no se reentrena. Esta prueba mide sensibilidad a la eliminación de entradas, no causalidad ni importancia de cada palabra.</p>'
        count=report.get('uncertainty_training',{}).get('rows',0)
        audit_html+=f'<p>Ejemplos adicionales de incertidumbre en entrenamiento: {count}. Cuando se usan etiquetas distribuidas, la pérdida de entrenamiento incluye su incertidumbre irreducible.</p>'
        first=h[0]['validation_loss'];last=h[-1]['validation_loss']
        audit_html+=f'<p>Validación: inicio {first:.4f}, final {last:.4f}. Se conserva la mejor época, no necesariamente la última. La diferencia con test también depende de sus textos y de la calibración; no debe interpretarse como mejora temporal.</p>'
    warning=('Estos datos proceden del generador sintético. Se reservan expresiones diferentes por partición, pero comparten las reglas del generador. No acreditan rendimiento en una industria real.' if report['data_origin']=='synthetic_demo' else 'La validez depende de cómo se separaron los datos suministrados. Mantenga organizaciones, autores o períodos relacionados en una sola partición.')
    text=f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Informe de decisiones</title>
<style>body{{font:16px system-ui;max-width:1080px;margin:40px auto;padding:0 22px;color:#172033;background:#f7f9fc}}h1,h2{{line-height:1.2}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;border-bottom:1px solid #dbe1ea;text-align:left}}img{{width:100%;max-width:850px}}article{{background:white;padding:20px;margin:20px 0;border-radius:10px}}dt{{font-weight:600}}dd{{margin:0 0 10px}}figcaption,.note{{color:#526078}}figure{{margin:24px 0}}</style>
<h1>Cerebro de decisiones: {esc(report['industry'])}</h1><p>Prueba con {report['split_sizes']['test']} casos. Pérdida media después de calibrar: <strong>{report['test_loss']:.5g}</strong>.</p>
<p>{esc(warning)}</p><p>La prueba funcional confirma que el modelo guardado conserva sus predicciones al recargarlo. La exactitud indica cuántas etiquetas coincide con los datos; no prueba que las acciones causen un resultado favorable.</p>
<table><tr><th>Pregunta</th><th>Exactitud</th><th>Referencia</th><th>Diferencia</th><th>Loss</th></tr>{''.join(rows)}</table>
<h2>Choice, Score y Noul</h2><p>Choice elige una opción. Score estima una posición entre 0 y el último nivel de la rúbrica; admite decimales. Noul estima la probabilidad de que una afirmación sea verdadera: 0,5 indica ambigüedad, no un grado intermedio.</p><p>Confidence usa 1 menos la entropía normalizada. No es probabilidad de acierto ni la fórmula privada de Jev. La revisión conserva el umbral min_probability sobre la opción más probable. Las matrices de Score comparan el nivel más probable; MAE evalúa el score continuo. Brier y loss: menor es mejor.</p><table><tr><th>Pregunta</th><th>Tipo</th><th>Loss</th><th>Brier</th><th>Lectura</th></tr>{''.join(typed_rows)}</table>{''.join(head_images)}
<h2>Aprendizaje y evaluación</h2><figure><img src="loss.png"><figcaption>Una pérdida menor representa más probabilidad asignada a las etiquetas correctas. Una brecha creciente entre entrenamiento y validación puede indicar sobreajuste.</figcaption></figure><figure><img src="accuracy.png"><figcaption>La referencia predice la clase más frecuente observada en entrenamiento. Ganarle es una comparación inicial, no una validación de producción.</figcaption></figure>{''.join(images)}
{assurance_html}{audit_html}<h2>Interpretación en escenarios</h2><p>Las acciones se proponen para el flujo de trabajo; no se ejecutan. Los criterios y preguntas proceden del contrato y no son explicaciones causales aprendidas.</p>{''.join(examples)}</html>'''
    (out/'report.html').write_text(text,encoding='utf-8')
