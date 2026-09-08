"""Offline evidence validation for the bounded recovery."""
from __future__ import annotations
import argparse,json
from pathlib import Path
TASK_ID='DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1'
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--run-id',required=True);a=p.parse_args();d=a.root.resolve()/'.agent/reports'/TASK_ID/a.run_id
 req=['recovery_command.json','status.json','report.json','run.log','pre_recovery_state.json','setter_journal.json','persistent_post_recovery_state.json','operation_current_state_comparison.json','topology_preservation_audit.json','phase3_idempotency_report.json'];bad=[x for x in req if not (d/x).is_file() or not (d/x).stat().st_size]
 r=json.loads((d/'report.json').read_text()) if not bad else {};ops=json.loads((d/'operation_current_state_comparison.json').read_text()).get('operations',[]) if not bad else [];p3=json.loads((d/'phase3_idempotency_report.json').read_text()) if not bad else {}
 if not r.get('ok') or r.get('setter_call_count')!=2 or r.get('save_call_count')!=0 or len(ops)!=36 or any(x.get('classification')!='CURRENT_TARGET' for x in ops):bad.append('recovery_contract')
 if p3!={'setters':0,'effective_mutations':0,'blend_operations':0,'modifier_mutations':0,'timeline_modified':False,'current_target':36}:bad.append('phase3_contract')
 result={'ok':not bad,'task_id':TASK_ID,'run_id':a.run_id,'failures':bad};(d/'recovery_validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return int(bool(bad))
if __name__=='__main__':raise SystemExit(main())
