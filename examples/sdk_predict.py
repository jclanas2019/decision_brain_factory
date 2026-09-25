"""Run from project root after `bash start.sh operate`. No credentials in source."""
import argparse
import json
from decision_brain_sdk import DecisionClient,ObserverClient,BrainError

def main():
    p=argparse.ArgumentParser();p.add_argument('--fleet',default='runtime/commerce-logistics');p.add_argument('--key',required=True);a=p.parse_args()
    try:
        with DecisionClient.from_fleet(a.fleet) as client:
            request=client.prepare('logistica.incidencia',{
                'horas_desviacion':48,'estado_entrega':'La entrega sigue pendiente dos días después de lo acordado.',
                'contexto':'Ejemplo ficticio de integración SDK.'},handoff={'dias_desde_compra':7},idempotency_key=a.key)
            decision=client.send(request)
            print(json.dumps(decision.to_dict(),ensure_ascii=False,indent=2))
        with ObserverClient.from_fleet(a.fleet) as observer:
            print('Traspasos visibles ahora:',json.dumps(observer.deliveries(decision.event_id),ensure_ascii=False))
            print('La entrega es asíncrona: consulta el panel si todavía no aparece.')
    except BrainError as exc:
        print(f'Error controlado: {exc.code}; HTTP={exc.status}; request_id={exc.request_id}')
        return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
