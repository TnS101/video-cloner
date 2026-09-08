"""Atomically publish the single read-only Step 3B.6D diagnostic command."""
from __future__ import annotations
import argparse, json, os, re
from pathlib import Path

TASK_ID="DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1"; FAILED_RUN_ID="20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"; PLAN_HASH="ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
def write(path, value):
 path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_name('.'+path.name+'.tmp'); temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8'); os.replace(temp,path)
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--run-id',required=True);a=p.parse_args();root=a.root.resolve()
 if not re.fullmatch(r'[0-9]{8}T[0-9]{9}Z_[0-9a-f]{32}',a.run_id): raise ValueError('run_id_format')
 q=root/'.agent/commands'; [ (q/x).mkdir(parents=True,exist_ok=True) for x in ('pending','running','completed','failed') ]
 if any(path for state in ('pending','running') for path in (q/state).glob('*.json')): raise ValueError('active_command')
 out=root/'.agent/reports'/TASK_ID/a.run_id
 if out.exists(): raise ValueError('report_exists')
 payload={'repository_root':str(root),'report_dir':str(out.relative_to(root)),'read_only':True,'failed_run_id':FAILED_RUN_ID,'plan_hash':PLAN_HASH,'plan_path':'.agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json','prestate_path':'.agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_EXECUTION_V1/20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379/four_target_pre_state_snapshot.json','forward_ledger_path':'.agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_FAILURE_FORENSICS_V1/forensics_20260802T154500934Z/forward_operation_ledger.json','expected_setter_count':0,'expected_save_count':0,'expected_modifier_mutation_count':0}
 rel=f'.agent/reports/{TASK_ID}/{a.run_id}'; cmd={'schema_version':1,'task':TASK_ID,'run_id':a.run_id,'module':'resolve_workspace/modules/step_3B_6D_read_only_state_capture.py','mode':'read_only_state_capture','status_path':f'{rel}/status.json','log_path':f'{rel}/run.log','report_path':f'{rel}/report.json','payload':payload}
 out.mkdir(parents=True);write(out/'diagnostic_command.json',cmd);write(q/'pending'/f'{TASK_ID}_{a.run_id}.json',cmd);print(json.dumps({'ok':True,'run_id':a.run_id,'command_count':1}))
if __name__=='__main__': main()
