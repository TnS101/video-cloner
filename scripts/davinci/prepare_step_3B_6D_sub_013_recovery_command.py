"""Publish exactly one bounded sub_013 recovery command."""
from __future__ import annotations
import argparse,json,os,re
from pathlib import Path
TASK_ID="DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1"; FAILED_RUN_ID="20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"; CAPTURE_RUN_ID="20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5"; PLAN_HASH="ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
def write(p,v): p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name('.'+p.name+'.tmp');t.write_text(json.dumps(v,indent=2)+'\n');os.replace(t,p)
def active_recovery_conflicts(queue: Path) -> list[Path]:
 return [path for state in ('pending','running') for path in (queue/state).glob('*'+TASK_ID+'*.json')]
def main():
 a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--run-id',required=True);x=a.parse_args();root=x.root.resolve()
 if not re.fullmatch(r'[0-9]{8}T[0-9]{9}Z_[0-9a-f]{32}',x.run_id):raise ValueError('run_id_format')
 q=root/'.agent/commands';[(q/s).mkdir(parents=True,exist_ok=True) for s in ('pending','running','completed','failed')]
 if active_recovery_conflicts(q):raise ValueError('conflicting_recovery_command')
 out=root/'.agent/reports'/TASK_ID/x.run_id
 if out.exists():raise ValueError('report_exists')
 plan='.agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json'; h=__import__('hashlib').sha256((root/plan).read_bytes()).hexdigest()
 allow=[{'cue_id':'sub_013','text':'out','item_identity':'VC_TEXTPLUS_0013_sub_013','property':'Center','local_frame':2,'timeline_frame':226,'raw_key_identifier':2,'current_value':{'1':0.506203705,'2':0.52842448,'3':0.0},'target_value':[0.50611111,0.5284375],'modifier':{'OUTS_ID':'Position','OUTS_DataType':'Point'}},{'cue_id':'sub_013','text':'out','item_identity':'VC_TEXTPLUS_0013_sub_013','property':'Size','local_frame':2,'timeline_frame':226,'raw_key_identifier':2,'current_value':0.08768857685550001,'target_value':0.087467395905,'modifier':{'OUTS_ID':'Value','OUTS_DataType':'Number'}}]
 rel=f'.agent/reports/{TASK_ID}/{x.run_id}';payload={'repository_root':str(root),'report_dir':rel,'failed_run_id':FAILED_RUN_ID,'read_only_capture_run_id':CAPTURE_RUN_ID,'plan_hash':PLAN_HASH,'plan_path':plan,'plan_file_sha256':h,'recovery_allowlist':allow,'forbidden_mutations':['Blend','DeleteModifier','AddModifier','Disconnect','ConnectTo','key_deletion','SaveProject']};cmd={'schema_version':1,'task':TASK_ID,'run_id':x.run_id,'module':'resolve_workspace/modules/step_3B_6D_sub_013_recovery.py','mode':'recovery','status_path':rel+'/status.json','log_path':rel+'/run.log','report_path':rel+'/report.json','payload':payload};out.mkdir(parents=True);write(out/'recovery_command.json',cmd);write(q/'pending'/(TASK_ID+'_'+x.run_id+'.json'),cmd);print(json.dumps({'ok':True,'command_count':1,'run_id':x.run_id}))
if __name__=='__main__':main()
