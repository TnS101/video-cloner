"""Offline validator for a completed Step 3B.6D read-only diagnostic."""
from __future__ import annotations
import argparse,json
from pathlib import Path
TASK_ID='DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1'; PLAN_HASH='ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf'
def load(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--run-id',required=True);a=p.parse_args();d=a.root.resolve()/'.agent/reports'/TASK_ID/a.run_id
 required=['diagnostic_command.json','status.json','report.json','run.log','project_timeline_identity_report.json','four_target_item_inventory.json','raw_center_size_state_snapshot.json','modifier_topology_snapshot.json','raw_keyframe_inventory.json','frame_address_mapping_report.json','operation_current_state_comparison.json','unexpected_state_inventory.json','target_classification_report.json','non_target_invariant_report.json','recovery_input_assessment.json']
 failures=[x for x in required if not (d/x).is_file() or (d/x).stat().st_size==0]; report=load(d/'report.json') if not failures else {}
 ops=load(d/'operation_current_state_comparison.json').get('operations',[]) if not failures else []
 if report.get('task_id')!=TASK_ID or report.get('run_id')!=a.run_id or report.get('plan_hash')!=PLAN_HASH or any(report.get(x)!=0 for x in ('setter_call_count','save_call_count','modifier_mutation_call_count','recovery_operation_count')) or report.get('timeline_modified') is not False: failures.append('read_only_contract')
 if len(ops)!=36 or len({(x.get('cue_id'),x.get('property'),x.get('local_frame')) for x in ops})!=36: failures.append('operation_classification')
 result={'ok':not failures,'task_id':TASK_ID,'run_id':a.run_id,'plan_hash':PLAN_HASH,'failures':failures};(d/'diagnostic_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result));return 1 if failures else 0
if __name__=='__main__': raise SystemExit(main())
