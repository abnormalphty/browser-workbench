"""Own only containers carrying this workbench's labels; never execute a shell."""
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx
import yaml

from .docker_env import command_env, download_url, engine_app, find_cli

# Bump with runtime/Dockerfile's label whenever files under runtime/ change.
RUNTIME_VERSION = '0.7.0'
IMAGE = 'local-browser-workbench:' + RUNTIME_VERSION
ROOT = Path(__file__).resolve().parent.parent
# First Docker Desktop start can sit behind its own agreement / sign-in pages.
ENGINE_WAIT_SECONDS = 600


def build_proxy_config(node: dict | None) -> dict:
    if node is None:
        raise ValueError('请先绑定节点；无代理测试需明确选择测试模式。')
    from .subscriptions import validate_node
    node = validate_node(node)
    node['name'] = 'environment-node'
    return {
        'mixed-port': 7890, 'allow-lan': False, 'bind-address': '127.0.0.1',
        'mode': 'rule', 'log-level': 'silent', 'ipv6': False,
        'proxies': [node], 'rules': ['MATCH,environment-node'],
    }


from .resources import ResourceControls,ResourceMonitor


class Runtime(ResourceControls):
    def __init__(self, store):
        self.store = store
        self._docker = None
        self.lock = threading.RLock()
        self.jobs = {}
        self.errors = {}
        self.build_state = 'idle'
        self.build_error = None
        self.prepare_phase = 'idle'
        self.prepare_progress = None
        self.scope = __import__('hashlib').sha256(str(store.data_dir).encode()).hexdigest()[:12]
        from .geography import Geography
        self.geography = Geography(store,self)
        self.account_checking=set()
        self.monitor=ResourceMonitor(self)

    def clipboard_text(self, env_id):
        obj = self._inspect(env_id)
        if not obj or not obj['State']['Running']:
            raise ValueError('请先打开浏览器环境。')
        if obj['State'].get('Paused'):raise ValueError('环境处于低功耗模式，请先唤醒。')
        # Reading the virtual desktop clipboard works for already-running older
        # images too. No browser restart or host clipboard access is involved.
        code = "import subprocess,json; p=subprocess.run(['xclip','-selection','clipboard','-out'],capture_output=True,timeout=3); print(json.dumps({'text':p.stdout.decode('utf-8',errors='replace') if p.returncode==0 and len(p.stdout)<=2097152 else '', 'too_large':len(p.stdout)>2097152},ensure_ascii=False))"
        response = self._run(['exec','--user','1000','--env','DISPLAY=:99',self.container_name(env_id),'python','-c',code],timeout=5,check=False)
        try:
            if response.returncode:raise ValueError()
            payload=json.loads(response.stdout)
            if payload.get('too_large'):raise ValueError('复制文字超过 2 MB，请通过文件传输取回。')
            value=payload['text']
            if not isinstance(value,str):raise ValueError()
            return value
        except (ValueError,KeyError) as exc:
            if str(exc)=='复制文字超过 2 MB，请通过文件传输取回。':raise
            raise ValueError('环境剪贴板暂时无法读取，请在环境内重新复制一次。')

    @property
    def docker(self):
        # Re-resolve while missing: Docker may be installed after we started.
        if not self._docker or not os.path.exists(self._docker):
            self._docker = find_cli()
        return self._docker

    def image_archive(self):
        """Prebuilt image shipped inside the app, so setup needs no registry."""
        path = os.environ.get('WORKBENCH_IMAGE_ARCHIVE')
        return path if path and os.path.isfile(path) else None

    def _run(self, args: list[str], timeout=20, check=True, input_text=None):
        docker = self.docker
        if not docker:
            raise ValueError('尚未找到 Docker，请先完成运行组件准备。')
        try:
            p = subprocess.run([docker, *args], capture_output=True, text=True, timeout=timeout, input=input_text, env=command_env(docker))
        except subprocess.TimeoutExpired as exc:
            raise ValueError('运行服务响应超时，请检查 Docker 是否已启动。') from exc
        if check and p.returncode:
            # docker errors may include labels/paths, so return our own message.
            raise ValueError('后台运行服务未能完成操作，请查看本机准备状态。')
        return p

    def status(self):
        installed=bool(self.docker);info=self.monitor.engine_info() if installed else {}
        image=False
        if info.get('ready'):
            try:image=self._run(['image','inspect',IMAGE],timeout=5,check=False).returncode==0
            except ValueError:pass
        app=engine_app()
        return {'docker_installed':installed,'docker_ready':bool(info.get('ready')),'image_ready':image,'build_state':self.build_state,'build_error':self.build_error,'prepare_phase':self.prepare_phase,'prepare_progress':self.prepare_progress,'engine_app':app['name'] if app else None,'image_bundled':bool(self.image_archive()),'docker_download_url':download_url(),'max_running':self.store.resource_settings()['max_running']}

    def container_name(self, env_id):
        self.store.valid_id(env_id)
        return 'local-browser-' + self.scope + '-' + env_id

    def environment_paths(self, env_id):
        self.store.valid_id(env_id)
        root = self.store.data_dir / 'environments' / env_id
        return root / 'config', root / 'profile'

    def _inspect(self, env_id):
        p = self._run(['inspect', self.container_name(env_id)], check=False)
        if p.returncode:
            return None
        obj = json.loads(p.stdout)[0]
        labels = obj.get('Config', {}).get('Labels', {})
        if labels.get('workbench.scope') != self.scope or labels.get('workbench.environment') != env_id:
            raise ValueError('环境归属校验失败。')
        return obj

    def containers(self):
        try:
            p = self._run(['ps', '-a', '--filter', f'label=workbench.scope={self.scope}', '--format', '{{json .}}'], timeout=5)
            return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
        except ValueError:
            return []

    def running_count(self):
        return len(self.occupied())

    def worker_address(self, env_id, port='8081/tcp'):
        obj = self._inspect(env_id)
        if not obj or not obj['State']['Running']:
            raise ValueError('环境尚未运行。')
        if obj['State'].get('Paused'):raise ValueError('环境处于低功耗模式，请先唤醒。')
        binding = obj.get('NetworkSettings', {}).get('Ports', {}).get(port)
        if not binding or binding[0].get('HostIp') != '127.0.0.1':
            raise ValueError('环境的本机连接尚未就绪。')
        return 'http://127.0.0.1:' + binding[0]['HostPort']

    def worker_secret(self, env_id):
        config, _ = self.environment_paths(env_id)
        return json.loads((config / 'launch.json').read_text())['worker_secret']

    def view_secret(self, env_id):
        config, _ = self.environment_paths(env_id)
        return json.loads((config / 'launch.json').read_text())['vnc_password']

    def state(self, env_id):
        state={'status':'stopped','error':self.errors.get(env_id),'memory_mb':None,'cpu_cores':None,'exit_ip':None,'test_mode':False,'account_checking':env_id in self.account_checking}
        if env_id in self.jobs and self.jobs[env_id].is_alive():state['status']='starting';return state
        try:
            obj=self._inspect(env_id)
            if not obj or not obj['State']['Running']:
                if state['error']:state['status']='error'
                return state
            metrics=self.monitor.collect().get(env_id,{})
            state.update(metrics)
            host=obj.get('HostConfig',{})
            state['effective_memory_limit_mb']=host.get('Memory',0)/1048576
            state['effective_cpu_limit']=host.get('NanoCpus',0)/1000000000
            if obj['State'].get('Paused'):
                state.update(status='paused',cpu_cores=0)
                if not state.get('memory_mb'):state.update(memory_mb=None,memory_stale=True)
                return state
            state['status']='starting'
            with httpx.Client(timeout=2,trust_env=False) as client:
                response=client.get(self.worker_address(env_id)+'/status',headers={'X-Worker-Token':self.worker_secret(env_id)})
            if response.status_code==200:
                info=response.json()
                state.update({k:info.get(k) for k in ['status','error','exit_ip','test_mode','fingerprint','url','title','timezone']})
        except (ValueError,OSError,httpx.HTTPError,KeyError,json.JSONDecodeError):pass
        return state

    def start(self, env_id, test_mode=False):
        with self.lock:
            env=self.store.get_environment(env_id);self._not_checking(env_id)
            if env.get('engine')!='firefox':raise ValueError('旧内核已移除，请新建标准 Firefox 环境；原数据保留。')
            if env_id in self.jobs and self.jobs[env_id].is_alive():return
            obj=self._inspect(env_id)
            if obj and obj['State']['Running']:
                if obj['State'].get('Paused'):self.resume(env_id)
                return
            if len(self.occupied())>=self.store.resource_settings()['max_running']:
                raise ValueError('已达到你设置的同时运行上限，请停止部分环境或调整上限。')
            status=self.status()
            if not status['docker_ready']:raise ValueError('请先启动 Docker Desktop。')
            if not status['image_ready']:raise ValueError('浏览器组件尚未准备好，请先点击准备运行组件。')
            self._validate_capacity(env);self._check_budget(env_id,env['memory_limit_mb'],include=True)
            proxy=build_proxy_config(self.store.get_node(env['node_id'])) if env['node_id'] else None
            if not proxy and not test_mode:raise ValueError('请先选择节点，或明确使用无代理测试模式。')
            self.errors.pop(env_id,None)
            job=threading.Thread(target=self._start_job,args=(env,proxy,not bool(env['node_id'])),daemon=True)
            self.jobs[env_id]=job;job.start()

    def _start_job(self, env, proxy, test_mode):
        env_id = env['id']
        try:
            timezone = None
            if env.get('timezone_mode') == 'node':
                timezone = self.geography.locate(env['node_id'])['timezone'] if env['node_id'] else 'Etc/UTC'
            self._run(['rm', '-f', self.container_name(env_id)], check=False)
            config_dir, profile_dir = self.environment_paths(env_id)
            for d in [config_dir, profile_dir]:
                d.mkdir(parents=True, exist_ok=True, mode=0o700)
            launch = {'environment_id': env_id, 'fingerprint_seed': env['fingerprint_seed'], 'engine': env.get('engine', 'firefox'), 'test_mode': test_mode, 'timezone':timezone, 'worker_secret': secrets.token_urlsafe(32), 'vnc_password': secrets.token_hex(4)}
            for name, payload in [('launch.json', json.dumps(launch)), ('proxy.yaml', yaml.safe_dump(proxy or {}, allow_unicode=True))]:
                path = config_dir / name
                path.write_text(payload)
                os.chmod(path, 0o600)
            self._run(['run', '-d', '--name', self.container_name(env_id), '--label', f'workbench.scope={self.scope}', '--label', f'workbench.environment={env_id}', '--shm-size', '512m', '--memory', str(env['memory_limit_mb'])+'m', '--memory-swap', str(env['memory_limit_mb']*2)+'m', '--cpus', str(env['cpu_limit']), '--pids-limit', '512', '--security-opt', 'no-new-privileges:true', '-p', '127.0.0.1::6080', '-p', '127.0.0.1::8081', '--mount', f'type=bind,source={config_dir},target=/config,readonly', '--mount', f'type=bind,source={profile_dir},target=/profile', IMAGE], timeout=60)
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                obj = self._inspect(env_id)
                if not obj or not obj['State']['Running']:
                    raise ValueError('浏览器进程启动失败，持久数据已保留。')
                try:
                    with httpx.Client(timeout=2, trust_env=False) as client:
                        r = client.get(self.worker_address(env_id) + '/status', headers={'X-Worker-Token': launch['worker_secret']})
                    info = r.json()
                    if info.get('status') == 'running':
                        return
                    if info.get('status') == 'error':
                        raise ValueError(info.get('error') or '浏览器启动失败。')
                except (httpx.HTTPError, json.JSONDecodeError):
                    pass
                time.sleep(1)
            raise ValueError('浏览器准备超时，可停止后重试；原有数据已保留。')
        except Exception as exc:
            self.errors[env_id] = str(exc) if isinstance(exc, ValueError) else '浏览器启动失败，原有数据已保留。'
            self._run(['rm', '-f', self.container_name(env_id)], check=False)

    def stop(self, env_id):
        self.store.get_environment(env_id)
        with self.lock:
            self._not_checking(env_id)
            if env_id in self.jobs and self.jobs[env_id].is_alive():
                raise ValueError('环境正在启动，请稍后再停止。')
            obj = self._inspect(env_id)
            if obj:
                if obj['State'].get('Paused'):self._run(['unpause',self.container_name(env_id)],timeout=10)
                self._run(['stop', '-t', '15', self.container_name(env_id)], timeout=25)
            self.errors.pop(env_id, None)
            self.monitor.invalidate()

    def delete(self, env_id):
        self.stop(env_id)
        self._run(['rm', '-f', self.container_name(env_id)], check=False)
        config, _ = self.environment_paths(env_id)
        if config.parent.exists():
            shutil.rmtree(config.parent)
        self.store.delete_environment(env_id)

    def build(self):
        with self.lock:
            if self.build_state == 'building':
                return
            self.build_state, self.build_error = 'building', None
            self.prepare_phase = 'checking'
            threading.Thread(target=self._prepare_job, daemon=True).start()

    def _open_desktop(self):
        if __import__('sys').platform != 'darwin':
            raise ValueError('请先启动本机 Docker 服务，再点击一键准备。')
        app = engine_app()
        if not app:
            raise ValueError('已找到 Docker 命令，但它的后台服务没有运行。请先启动你使用的 Docker 服务，再点击重试。')
        result = subprocess.run(['open','-a',app['path']], capture_output=True, timeout=15)
        if result.returncode:
            raise ValueError(f"未能打开 {app['name']}，请检查它是否已正确安装。")

    def _prepare_job(self, attempts=300):
        try:
            status = self.status()
            if not status['docker_installed']:
                raise ValueError('请先安装 Docker Desktop。装好并打开后，工作台会自动继续准备。')
            if not status['docker_ready']:
                self.prepare_phase = 'starting_docker'
                self._open_desktop()
                self.prepare_phase = 'waiting_docker'
                deadline = time.monotonic() + ENGINE_WAIT_SECONDS
                for _ in range(attempts):
                    if time.monotonic() >= deadline:
                        break
                    # A cached offline result must not delay or stop the chain.
                    self.monitor.engine_info(force=True)
                    status = self.status()
                    if status['docker_ready']:
                        break
                    time.sleep(2)
                if not status['docker_ready']:
                    raise ValueError('Docker 仍未就绪。请在 Docker 窗口完成首次启动提示，然后回这里重试。')
            if status['image_ready']:
                self.build_state, self.prepare_phase = 'ready', 'ready'
                self.build_error = None
                return
            archive = self.image_archive()
            if archive:
                self.prepare_phase = 'loading_image'
                try:
                    return self._load_image(archive)
                except ValueError:
                    # A damaged archive should not strand the user; building
                    # from the bundled Dockerfile still works when online.
                    pass
            self.prepare_phase = 'building'
            self._build_job()
            if archive and self.build_state == 'error':
                self.build_error = '内置浏览器组件未能载入，联网构建也没有完成。请重试；详情见本机 build.log。'
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            self.build_error = str(exc) if isinstance(exc,ValueError) else '准备未能完成，请检查 Docker 是否已正常启动，然后重试。'
            self.build_state, self.prepare_phase = 'error', 'error'

    def _load_image(self, archive):
        log = self.store.data_dir / 'build.log'
        docker = self.docker
        total = max(os.path.getsize(archive), 1)
        self.prepare_progress = 0
        try:
            with open(archive, 'rb') as source, log.open('w') as output:
                os.chmod(log, 0o600)
                # docker load accepts gzip/xz/zstd archives; stream it so the
                # interface can show how far the one-time import has got.
                process = subprocess.Popen([docker, 'load'], stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, env=command_env(docker))
                try:
                    sent = 0
                    while chunk := source.read(1 << 20):
                        process.stdin.write(chunk)
                        sent += len(chunk)
                        self.prepare_progress = min(99, sent * 100 // total)
                    process.stdin.close()
                    code = process.wait(timeout=1800)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    process.kill()
                    process.wait()
                    raise ValueError('浏览器组件载入中断，请重试。') from exc
        finally:
            self.prepare_progress = None
        if code or self._run(['image','inspect',IMAGE],timeout=10,check=False).returncode:
            raise ValueError('浏览器组件载入失败，可重试；详情见本机 build.log。')
        self.build_state, self.prepare_phase, self.build_error = 'ready', 'ready', None

    def stop_all(self, wait_for_starting=30):
        """Stop every started environment at once, e.g. when the app quits."""
        deadline = time.monotonic() + wait_for_starting
        for job in list(self.jobs.values()):
            if job.is_alive():
                job.join(max(0, deadline - time.monotonic()))
        with self.lock:
            objects = self.active_objects()
            paused = [self.container_name(i) for i, o in objects.items() if o['State'].get('Paused')]
            names = [self.container_name(i) for i in objects]
            if paused:
                self._run(['unpause', *paused], timeout=20, check=False)
            # One docker stop call stops containers concurrently; each gets the
            # same grace period the single-environment stop uses.
            failed = self._run(['stop', '-t', '15', *names], timeout=60, check=False).returncode if names else 0
            self.monitor.invalidate()
        return {'stopped': len(names), 'ok': not failed}

    def _build_job(self):
        log = self.store.data_dir / 'build.log'
        try:
            if not self.status()['docker_ready']:
                raise ValueError('Docker 尚未启动，请先打开 Docker Desktop。')
            with log.open('w') as output:
                os.chmod(log, 0o600)
                p = subprocess.run([self.docker, 'build', '-t', IMAGE, str(ROOT / 'runtime')], stdout=output, stderr=subprocess.STDOUT, timeout=1800, env=command_env(self.docker))
            if p.returncode:
                raise ValueError('浏览器组件构建失败，可重试；详情见本机 build.log。')
            self.build_state, self.prepare_phase = 'ready', 'ready'
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            self.build_error = str(exc) if isinstance(exc, ValueError) else '构建超时或无法启动，请重试。'
            self.build_state, self.prepare_phase = 'error', 'error'
