"""User-initiated account metadata, separate from browser session secrets."""
import json,time
from pathlib import Path


def check_account(runtime,env_id):
 store=runtime.store;store.get_environment(env_id)
 with runtime.lock:
  runtime._not_checking(env_id)
  obj=runtime._inspect(env_id)
  if not obj or not obj['State']['Running']:raise ValueError('请先启动环境并登录 Claude，再核对账号。')
  if obj['State'].get('Paused'):raise ValueError('请先唤醒环境，再核对账号。')
  if env_id in runtime.jobs and runtime.jobs[env_id].is_alive():raise ValueError('请等待环境启动完成。')
  runtime.account_checking.add(env_id)
 try:
  source=(Path(__file__).resolve().parents[1]/'runtime/account_info.py').read_text()
  result=runtime._run(['exec','-i','--user','1000','--env','DISPLAY=:99',runtime.container_name(env_id),'python','-'],timeout=60,check=False,input_text=source)
  data=json.loads(result.stdout) if result.returncode==0 else {}
  if not isinstance(data,dict):data={}
  now=time.time();prior=store.account_info(env_id)
  verified=data.get('verified') is True and (data.get('plan') in ('free','pro','max','team','enterprise') or data.get('status') in ('active','blocked','logged_out'))
  value={**prior,'last_attempt':now,'verified':verified,'note':'本次未能确认，保留上次记录；可打开账单页核对后手动标记。'}
  if verified:
   plan=data.get('plan');status=data.get('status')
   if plan in ('free','pro','max','team','enterprise'):value.update(plan=plan,plan_source='page',plan_checked_at=now)
   if status in ('active','blocked','logged_out'):value.update(status=status,status_source='page',status_checked_at=now)
   value.update(source='page',checked_at=now,note='已核对 Claude 设置页。')
  store.set_setting('account:'+env_id,value)
  return value
 except (ValueError,OSError,json.JSONDecodeError):
  prior=store.account_info(env_id)
  value={**prior,'last_attempt':time.time(),'verified':False,'note':'本次无法核对，保留上次记录。'}
  store.set_setting('account:'+env_id,value);return value
 finally:
  with runtime.lock:runtime.account_checking.discard(env_id)
