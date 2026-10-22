"""Read explicit Claude account information in a temporary Firefox window.

No cookie database or browser debugging connection is used. The X11 PRIMARY
selection is read without copying into or modifying CLIPBOARD, preserving all
clipboard formats and sizes. Only structured metadata leaves the desktop.
"""
import json,re,subprocess,time,signal
from urllib.parse import urlsplit
from pathlib import Path

TARGET='https://claude.ai/settings/billing'


def account_url_allowed(url):
 try:
  u=urlsplit(url)
  return u.scheme=='https' and u.hostname in ('claude.ai','www.claude.ai') and u.port in (None,443) and (u.path=='/settings' or u.path.startswith('/settings/') or u.path in ('/login','/login/'))
 except ValueError:return False


def parse_account_page(url,text):
 result={'plan':'unknown','status':'unknown','source':'page','verified':False,'note':'未找到明确的当前套餐或账号状态，请在浏览器中核对后手动标记。'}
 if not account_url_allowed(url):return result
 text=str(text)[:200000]
 if re.search(r'(?m)^\s*(?:Unfortunately,\s*)?your account (?:has been |is )(?:disabled|banned|suspended)\b|您的(?:帐|账)(?:号|户)(?:已被|已经|已)(?:禁用|封禁|停用)|你的(?:帐|账)(?:号|户)(?:已被|已经|已)(?:禁用|封禁|停用)',text,re.I):
  return {**result,'status':'blocked','verified':True,'note':'页面明确提示账号已停用或封禁。'}
 patterns=[r'(?:your\s+)?current\s+(?:plan|subscription)\s*[:：\-]?\s*(?:claude\s+)?(free|pro|max|team|enterprise)\b',r'(?:you are|you\u2019re|you\x27re)\s+(?:currently\s+)?(?:on|subscribed to)\s+(?:the\s+)?(?:claude\s+)?(free|pro|max|team|enterprise)\b',r'(?:当前套餐|目前套餐|当前计划|目前方案|目前方案為|当前订阅|当前方案)\s*[:：]?\s*(?:claude\s+)?(free|pro|max|team|enterprise)\b']
 for pattern in patterns:
  match=re.search(pattern,text,re.I)
  if match:return {**result,'plan':match[1].lower(),'status':'active','verified':True,'note':'已从 Claude 设置页的当前套餐提示核对。'}
 # Use a paid-plan card only when its own nearby control manages an existing
 # subscription. Upgrade cards mentioning Pro or Max alone are never evidence.
 match=re.search(r'\bClaude\s+(Pro|Max|Team|Enterprise)\b\s*(?:\([^\n]{0,30}\))?\s*(?:\n[^\n]{0,80}){0,2}\n\s*(?:Manage subscription|管理订阅|管理訂閱)\b',text,re.I)
 if match:return {**result,'plan':match[1].lower(),'status':'active','verified':True,'note':'已核对设置页的当前订阅管理区域。'}
 if urlsplit(url).path.rstrip('/')=='/login' and re.search('Continue with Google|Enter your email|使用 Google 继续|输入你的邮箱|输入您的邮箱',text,re.I):
  return {**result,'status':'logged_out','verified':True,'note':'当前窗口停在 Claude 登录页。'}
 return result


def _run(*args,timeout=4):
 return subprocess.run(args,capture_output=True,check=True,timeout=timeout).stdout



def _windows():
 try:return set(_run('xdotool','search','--onlyvisible','--class','firefox').decode().split())
 except subprocess.CalledProcessError:return set()


def _selected_text():
 # Firefox on X11 exports selected text as PRIMARY. Ctrl+C would alter
 # CLIPBOARD and lose rich formats; never send it during account checks.
 time.sleep(.2)
 try:return _run('xclip','-selection','primary','-out',timeout=2).decode('utf-8',errors='replace')[:200000]
 except (subprocess.SubprocessError,OSError):return ''


def probe_account(target=TARGET,test_origin=None):
 # The fixture escape hatch is callable only inside explicitly disposable
 # test-mode environments; the public workbench API never accepts a target URL.
 if test_origin and not json.loads(Path('/run/workbench/launch.json').read_text()).get('test_mode'):
  raise ValueError('Fixture origins require test mode')
 def timed_out(*_):raise TimeoutError('Account check timed out')
 old_alarm=signal.signal(signal.SIGALRM,timed_out);signal.alarm(35)
 before=_windows();original=None;created=None
 try:
  if not before:raise ValueError('Browser is not available')
  active=_run('xdotool','getactivewindow').decode().strip()
  original=active if active in before else sorted(before)[0]
  _run('xdotool','windowactivate','--sync',original)
  _run('xdotool','key','--clearmodifiers','ctrl+n')
  for _ in range(30):
   extra=_windows()-before
   if len(extra)==1:created=extra.pop();break
   if len(extra)>1:raise ValueError('Window selection changed')
   time.sleep(.1)
  if not created:raise ValueError('Account window not available')
  _run('xdotool','windowactivate','--sync',created)
  _run('xdotool','key','--clearmodifiers','ctrl+l')
  _run('xdotool','type','--clearmodifiers','--delay','1',target)
  _run('xdotool','key','--clearmodifiers','Return')
  deadline=time.monotonic()+18;result=parse_account_page('', '')
  time.sleep(2)
  while time.monotonic()<deadline:
   if created not in _windows():raise ValueError('Account window was closed')
   _run('xdotool','windowactivate','--sync',created)
   _run('xdotool','key','--clearmodifiers','ctrl+l')
   # Address-bar Ctrl+L selects visually but does not update PRIMARY.
   _run('xdotool','key','--clearmodifiers','End','shift+Home');url=_selected_text().strip()
   fixture=bool(test_origin and url.startswith(test_origin+'/'))
   if account_url_allowed(url) or fixture:
    _run('xdotool','key','--clearmodifiers','F6')
    _run('xdotool','key','--clearmodifiers','ctrl+a')
    page=_selected_text()
    result=parse_account_page(TARGET if fixture else url,page)
    if result['verified']:return result
   time.sleep(1.5)
  return result
 except Exception:
  return {'plan':'unknown','status':'unknown','source':'page','verified':False,'note':'无法核对。请确认环境已登录 Claude，或打开账单页查看后手动标记。'}
 finally:
  signal.alarm(0);signal.signal(signal.SIGALRM,old_alarm)
  if created and created in _windows():
   try:_run('wmctrl','-i','-c',created)
   except Exception:pass
  if original and original in _windows():
   try:_run('xdotool','windowactivate','--sync',original)
   except Exception:pass


if __name__=='__main__':print(json.dumps(probe_account(),ensure_ascii=False))
