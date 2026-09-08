import importlib.util
from pathlib import Path

ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent/'resolve_workspace').is_dir())
MODULE=ROOT/'resolve_workspace/modules/step_3B_6D_sub_013_recovery.py'
PREPARER=Path(__file__).resolve().parents[1]/'scripts/davinci/prepare_step_3B_6D_sub_013_recovery_command.py'
spec=importlib.util.spec_from_file_location('recovery_preparer',PREPARER)
preparer=importlib.util.module_from_spec(spec);spec.loader.exec_module(preparer)

def test_recovery_is_a_fixed_two_operation_raw_key_contract():
 s=MODULE.read_text(encoding='utf-8'); assert 'raw_key_identifier' in s and 'inp[raw]=op["target_value"]' in s
 assert s.count('"cue_id":"sub_013"')==2 and 'CURRENT_OTHER' in s and 'full_plan_readback' in s
def test_recovery_forbids_topology_and_save_operations():
 s=MODULE.read_text(encoding='utf-8')
 for forbidden in ('DeleteModifier','AddModifier','Disconnect','ConnectTo','SaveProject','RemoveKeyFrame'): assert forbidden not in s
def test_phase_three_is_zero_mutation_and_preparer_is_single_queue_command():
 s=MODULE.read_text(encoding='utf-8'); p=PREPARER.read_text(encoding='utf-8')
 assert '"setters":0,"effective_mutations":0' in s and "conflicting_recovery_command" in p and "pending" in p

def queue(tmp_path):
 root=tmp_path/'repository'; q=root/'.agent/commands'
 for state in ('pending','running','completed','failed'):(q/state).mkdir(parents=True)
 return q
def command(path): path.write_text('{}\n',encoding='utf-8')

def test_empty_glob_iterators_are_not_conflicts(tmp_path):
 assert preparer.active_recovery_conflicts(queue(tmp_path)) == []
def test_matching_pending_recovery_command_is_a_conflict(tmp_path):
 q=queue(tmp_path); command(q/'pending'/(preparer.TASK_ID+'_x.json'))
 assert [p.parent.name for p in preparer.active_recovery_conflicts(q)] == ['pending']
def test_matching_running_recovery_command_is_a_conflict(tmp_path):
 q=queue(tmp_path); command(q/'running'/(preparer.TASK_ID+'_x.json'))
 assert [p.parent.name for p in preparer.active_recovery_conflicts(q)] == ['running']
def test_both_active_locations_are_deterministically_enumerated(tmp_path):
 q=queue(tmp_path); command(q/'pending'/(preparer.TASK_ID+'_a.json')); command(q/'running'/(preparer.TASK_ID+'_b.json'))
 assert [p.parent.name for p in preparer.active_recovery_conflicts(q)] == ['pending','running']
def test_unrelated_and_historical_commands_are_not_active_recovery_conflicts(tmp_path):
 q=queue(tmp_path); command(q/'pending'/'OTHER_TASK_x.json'); command(q/'completed'/(preparer.TASK_ID+'_old.json')); command(q/'failed'/(preparer.TASK_ID+'_old.json'))
 assert preparer.active_recovery_conflicts(q) == []
def test_conflict_query_returns_concrete_paths_not_a_truthy_glob_iterator(tmp_path):
 result=preparer.active_recovery_conflicts(queue(tmp_path))
 assert isinstance(result,list) and not result
