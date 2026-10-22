"""Resource quotas and batched, scope-limited Docker telemetry."""
import math,os,re,subprocess,threading,time,json


def validate_limits(data):
 cpu=data.get('cpu_limit',2);memory=data.get('memory_limit_mb',2048)
 if isinstance(cpu,bool) or not isinstance(cpu,(float,int)) or not math.isfinite(cpu) or not .25<=cpu<=64:
  raise ValueError('CPU 上限应为 0.25—64 核。')
 if isinstance(memory,bool) or not isinstance(memory,int) or not 512<=memory<=262144:
  raise ValueError('内存上限应为 512—262144 MB。')
 return {'cpu_limit':float(cpu),'memory_limit_mb':memory}


def memory_mb(value):
 m=re.fullmatch(r'\s*([\d.]+)\s*(B|KiB|MiB|GiB|TiB|KB|MB|GB|TB)\s*',value)
 if not m:raise ValueError('Unknown memory unit')
 return float(m[1])*{'B':1/1048576,'KiB':1/1024,'MiB':1,'GiB':1024,'TiB':1048576,'KB':1000/1048576,'MB':1000000/1048576,'GB':1000000000/1048576,'TB':1000000000000/1048576}[m[2]]


def parse_stats(row):
 usage,limit=row['MemUsage'].split('/')
 return {'cpu_cores':float(row['CPUPerc'].rstrip('%'))/100,'memory_mb':round(memory_mb(usage),2),'memory_limit_mb':round(memory_mb(limit),2),'pids':int(row.get('PIDs') or 0),'sampled_at':time.time(),'available':True}


def occupied_ids(objects,pending):
 return {identity for identity,obj in objects.items() if obj.get('State',{}).get('Running')}|set(pending)


class ResourceMonitor:
 def __init__(self,runtime):
  self.runtime=runtime;self.lock=threading.RLock();self.metrics={};self.sampled_at=0;self.info={};self.info_at=0
  self.host={'cpu_count':os.cpu_count(),'memory_mb':None}
  if __import__('sys').platform=='darwin':
   try:self.host['memory_mb']=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True,timeout=2,stderr=subprocess.DEVNULL))//1048576
   except (OSError,ValueError,subprocess.SubprocessError):pass
 def invalidate(self):
  self.sampled_at=0
 def engine_info(self,force=False):
  with self.lock:
   if not force and self.info_at and time.time()-self.info_at<20:return dict(self.info)
   try:
    p=self.runtime._run(['info','--format','{{json .}}'],timeout=5,check=False)
    if p.returncode:raise ValueError()
    d=json.loads(p.stdout)
    self.info={'ready':True,'cpu_count':d['NCPU'],'memory_mb':int(d['MemTotal'])//1048576,'version':d['ServerVersion']}
   except (ValueError,KeyError,TypeError,OSError):self.info={'ready':False,'cpu_count':None,'memory_mb':None}
   self.info_at=time.time();return dict(self.info)
 def collect(self,force=False):
  with self.lock:
   if not force and self.sampled_at and time.time()-self.sampled_at<4:return dict(self.metrics)
   env_ids={e['id'] for e in self.runtime.store.list_environments()}
   names=[self.runtime.container_name(identity) for identity in env_ids]
   if not names:self.metrics={};self.sampled_at=time.time();return {}
   try:
    result=self.runtime._run(['stats','--no-stream','--format','{{json .}}',*names],timeout=8,check=False)
    metrics={}
    for line in result.stdout.splitlines():
     try:
      row=json.loads(line);name=row.get('Name') or row.get('Container','');identity=name.rsplit('-',1)[-1]
      if identity not in env_ids:continue
      value=parse_stats(row)
      # Paused containers can produce a 0B telemetry row. Keep the last
      # observed memory, clearly marked stale rather than implying it was freed.
      if value['memory_mb']==0 and self.metrics.get(identity,{}).get('memory_mb'):
       value['memory_mb']=self.metrics[identity]['memory_mb'];value['memory_stale']=True
      metrics[identity]=value
     except (ValueError,TypeError,KeyError):continue
    self.metrics=metrics;self.sampled_at=time.time()
   except (ValueError,OSError):self.sampled_at=time.time();self.metrics={}
   return dict(self.metrics)

class ResourceControls:
 def active_objects(self):
  objects={}
  prefix='local-browser-'+self.scope+'-'
  for item in self.containers():
   name=item.get('Names','')
   if not name.startswith(prefix):continue
   identity=name[len(prefix):]
   try:self.store.valid_id(identity)
   except ValueError:continue
   if item.get('State') not in ('running','paused') and '(Paused)' not in item.get('Status',''):continue
   obj=self._inspect(identity)
   if obj and obj['State']['Running']:objects[identity]=obj
  return objects
 def occupied(self,objects=None):
  return occupied_ids(self.active_objects() if objects is None else objects,[key for key,job in list(self.jobs.items()) if job.is_alive()])
 def _not_checking(self,env_id):
  if env_id in self.account_checking:raise ValueError('正在核对账号，请等待完成后再操作环境。')
 def _validate_capacity(self,limits):
  info=self.monitor.engine_info()
  if info.get('ready'):
   if limits['cpu_limit']>info['cpu_count']:raise ValueError(f"CPU 上限不能超过运行组件的 {info['cpu_count']} 核。")
   if limits['memory_limit_mb']>info['memory_mb']-512:raise ValueError('该内存额度超过运行组件可分配容量。')
 def _check_budget(self,env_id,new_memory=None,include=False):
  objects=self.active_objects();ids=self.occupied(objects)
  if include:ids.add(env_id)
  limits={e['id']:e['memory_limit_mb'] for e in self.store.list_environments()}
  total=0
  for identity in ids:
   if identity==env_id and new_memory is not None:value=new_memory
   else:value=objects.get(identity,{}).get('HostConfig',{}).get('Memory',0)/1048576 or limits.get(identity,2048)
   total+=value
  info=self.monitor.engine_info()
  if info.get('ready') and total>info['memory_mb']-512:
   raise ValueError('已启动环境的内存上限合计超过可分配容量。请减少单环境额度或停止部分环境。')
 def resource_overview(self):
  engine=self.monitor.engine_info();metrics=self.monitor.collect();objects=self.active_objects()
  ids=self.occupied(objects);allocations=sum((objects.get(i,{}).get('HostConfig',{}).get('Memory',0)/1048576 or self.store.get_environment(i)['memory_limit_mb']) for i in ids)
  active_metrics=[metrics[i] for i in objects if i in metrics]
  cpu=sum(0 if objects[i]['State'].get('Paused') else metrics.get(i,{}).get('cpu_cores',0) for i in objects)
  memory_complete=len(active_metrics)==len(objects) and all(metrics.get(i,{}).get('memory_mb') is not None and not (o['State'].get('Paused') and metrics.get(i,{}).get('memory_mb')==0) for i,o in objects.items())
  return {'host':dict(self.monitor.host),'engine':engine,'max_running':self.store.resource_settings()['max_running'],'occupied':len(ids),'paused':sum(bool(o['State'].get('Paused')) for o in objects.values()),'cpu_cores':round(cpu,3) if len(active_metrics)==len(objects) and engine.get('ready') else None,'memory_mb':round(sum(m['memory_mb'] for m in active_metrics),2) if memory_complete and engine.get('ready') else None,'allocated_memory_mb':round(allocations),'memory_budget_mb':max(0,(engine.get('memory_mb') or 0)-512),'sampled_at':self.monitor.sampled_at,'metrics_complete':memory_complete}
 def set_max_running(self,data):
  value=data.get('max_running')
  if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=100:raise ValueError('同时运行上限应为 1—100 个环境。')
  with self.lock:
   if value<len(self.occupied()):raise ValueError('上限不能少于当前已启动数量，请先停止部分环境。')
   return self.store.save_resource_settings(data)
 def set_limits(self,env_id,data):
  limits=validate_limits(data)
  with self.lock:
   self._not_checking(env_id);self.store.get_environment(env_id)
   if env_id in self.jobs and self.jobs[env_id].is_alive():raise ValueError('请等待环境启动完成。')
   self._validate_capacity(limits);obj=self._inspect(env_id)
   if obj and obj['State']['Running']:
    self._check_budget(env_id,limits['memory_limit_mb'])
    old_mb=obj.get('HostConfig',{}).get('Memory',0)/1048576
    if old_mb and limits['memory_limit_mb']<old_mb:
     if obj['State'].get('Paused'):raise ValueError('低功耗环境保留内存，请先唤醒或停止后再缩减内存额度。')
     usage=self.monitor.collect(force=True).get(env_id,{}).get('memory_mb')
     if usage is None or limits['memory_limit_mb']<usage*1.15+64:
      raise ValueError('新额度接近或低于当前内存占用，请提高额度或停止环境后修改。')
    self._run(['update','--cpus',str(limits['cpu_limit']),'--memory',str(limits['memory_limit_mb'])+'m','--memory-swap',str(limits['memory_limit_mb']*2)+'m',self.container_name(env_id)],timeout=10)
   value=self.store.set_environment_limits(env_id,limits);self.monitor.invalidate();return value
 def pause(self,env_id):
  with self.lock:
   self._not_checking(env_id);self.store.get_environment(env_id)
   if env_id in self.jobs and self.jobs[env_id].is_alive():raise ValueError('请等待环境启动完成。')
   obj=self._inspect(env_id)
   if not obj or not obj['State']['Running']:raise ValueError('请先启动环境。')
   if not obj['State'].get('Paused'):
    self.monitor.collect(force=True)
    self._run(['pause',self.container_name(env_id)],timeout=10)
   self.monitor.invalidate()
 def resume(self,env_id):
  with self.lock:
   self._not_checking(env_id);self.store.get_environment(env_id);obj=self._inspect(env_id)
   if not obj or not obj['State']['Running']:raise ValueError('环境已停止，请重新启动。')
   if obj['State'].get('Paused'):self._run(['unpause',self.container_name(env_id)],timeout=10)
   self.monitor.invalidate()
