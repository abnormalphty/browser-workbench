"""Approximate labels, verified exit geography, and IANA time zones."""
from datetime import datetime
import json
import math
import re
import tempfile
import threading
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# City coordinates are display points; a name match is never labelled an exit measurement.
ROWS = [
('tokyo','东京','JP',35.68,139.69,'Asia/Tokyo','東京|日本|japan|tokyo|🇯🇵'),
('seoul','首尔','KR',37.57,126.98,'Asia/Seoul','首爾|首尔|韩国|韓國|korea|seoul|🇰🇷'),
('taipei','台北','TW',25.03,121.56,'Asia/Taipei','台北|臺北|台湾|台灣|臺灣|taiwan|taipei|🇹🇼'),
('hong-kong','香港','HK',22.32,114.17,'Asia/Hong_Kong','香港|hong.?kong|🇭🇰'),
('singapore','新加坡','SG',1.35,103.82,'Asia/Singapore','新加坡|狮城|獅城|singapore|🇸🇬'),
('new-york','纽约','US',40.71,-74.01,'America/New_York','纽约|紐約|new.?york'),
('los-angeles','洛杉矶','US',34.05,-118.24,'America/Los_Angeles','洛杉矶|洛杉磯|los.?angeles'),
('san-jose','圣何塞','US',37.34,-121.89,'America/Los_Angeles','圣何塞|聖何塞|san.?jose'),
('san-francisco','旧金山','US',37.77,-122.42,'America/Los_Angeles','旧金山|舊金山|san.?francisco'),
('chicago','芝加哥','US',41.88,-87.63,'America/Chicago','芝加哥|chicago'),
('dallas','达拉斯','US',32.78,-96.8,'America/Chicago','达拉斯|達拉斯|dallas'),
('denver','丹佛','US',39.74,-104.99,'America/Denver','丹佛|denver'),
('phoenix','凤凰城','US',33.45,-112.07,'America/Phoenix','凤凰城|鳳凰城|phoenix'),
('honolulu','檀香山','US',21.31,-157.86,'Pacific/Honolulu','檀香山|夏威夷|hawaii|honolulu'),
('london','伦敦','GB',51.51,-0.13,'Europe/London','伦敦|倫敦|英国|英國|london|united.?kingdom|🇬🇧'),
('berlin','柏林','DE',52.52,13.41,'Europe/Berlin','柏林|德国|德國|germany|berlin|🇩🇪'),
('frankfurt','法兰克福','DE',50.11,8.68,'Europe/Berlin','法兰克福|法蘭克福|frankfurt'),
('paris','巴黎','FR',48.86,2.35,'Europe/Paris','巴黎|法国|法國|paris|france|🇫🇷'),
('amsterdam','阿姆斯特丹','NL',52.37,4.9,'Europe/Amsterdam','阿姆斯特丹|荷兰|荷蘭|amsterdam|netherlands|🇳🇱'),
('zurich','苏黎世','CH',47.38,8.54,'Europe/Zurich','苏黎世|蘇黎世|瑞士|switzerland|zurich|🇨🇭'),
('stockholm','斯德哥尔摩','SE',59.33,18.07,'Europe/Stockholm','瑞典|斯德哥尔摩|sweden|stockholm|🇸🇪'),
('helsinki','赫尔辛基','FI',60.17,24.94,'Europe/Helsinki','芬兰|芬蘭|赫尔辛基|finland|helsinki|🇫🇮'),
('madrid','马德里','ES',40.42,-3.7,'Europe/Madrid','西班牙|马德里|spain|madrid|🇪🇸'),
('milan','米兰','IT',45.46,9.19,'Europe/Rome','意大利|米兰|米蘭|italy|milan|🇮🇹'),
('moscow','莫斯科','RU',55.76,37.62,'Europe/Moscow','莫斯科|moscow'),
('vladivostok','海参崴','RU',43.12,131.89,'Asia/Vladivostok','海参崴|海參崴|vladivostok'),
('toronto','多伦多','CA',43.65,-79.38,'America/Toronto','多伦多|多倫多|toronto'),
('vancouver','温哥华','CA',49.28,-123.12,'America/Vancouver','温哥华|溫哥華|vancouver'),
('sydney','悉尼','AU',-33.87,151.21,'Australia/Sydney','悉尼|雪梨|sydney'),
('melbourne','墨尔本','AU',-37.81,144.96,'Australia/Melbourne','墨尔本|墨爾本|melbourne'),
('perth','珀斯','AU',-31.95,115.86,'Australia/Perth','珀斯|perth'),
('auckland','奥克兰','NZ',-36.85,174.76,'Pacific/Auckland','新西兰|新西蘭|奥克兰|auckland|new.?zealand|🇳🇿'),
('mumbai','孟买','IN',19.08,72.88,'Asia/Kolkata','印度|孟买|孟買|india|mumbai|🇮🇳'),
('bangkok','曼谷','TH',13.76,100.5,'Asia/Bangkok','泰国|泰國|曼谷|thailand|bangkok|🇹🇭'),
('kuala-lumpur','吉隆坡','MY',3.14,101.69,'Asia/Kuala_Lumpur','马来西亚|馬來西亞|吉隆坡|malaysia|kuala|🇲🇾'),
('manila','马尼拉','PH',14.6,120.98,'Asia/Manila','菲律宾|菲律賓|马尼拉|philippines|manila|🇵🇭'),
('jakarta','雅加达','ID',-6.21,106.85,'Asia/Jakarta','雅加达|雅加達|jakarta'),
('dubai','迪拜','AE',25.2,55.27,'Asia/Dubai','阿联酋|阿聯酋|迪拜|dubai|🇦🇪'),
('istanbul','伊斯坦布尔','TR',41.01,28.98,'Europe/Istanbul','土耳其|伊斯坦布尔|turkey|istanbul|🇹🇷'),
('tel-aviv','特拉维夫','IL',32.08,34.78,'Asia/Jerusalem','以色列|特拉维夫|israel|tel.?aviv|🇮🇱'),
('sao-paulo','圣保罗','BR',-23.55,-46.63,'America/Sao_Paulo','圣保罗|聖保羅|sao.?paulo'),
('mexico-city','墨西哥城','MX',19.43,-99.13,'America/Mexico_City','墨西哥城|mexico.?city'),
('johannesburg','约翰内斯堡','ZA',-26.2,28.04,'Africa/Johannesburg','南非|约翰内斯堡|south.?africa|johannesburg|🇿🇦'),
('shanghai','上海','CN',31.23,121.47,'Asia/Shanghai','上海|中国|中國|shanghai|🇨🇳'),
]
PLACES={row[0]:dict(id=row[0],label=row[1],country_code=row[2],lat=row[3],lon=row[4],timezone=row[5]) for row in ROWS}
COUNTRIES=[('US','美国',39,-98,'美国|美國|united.?states|🇺🇸'),('CA','加拿大',57,-106,'加拿大|canada|🇨🇦'),('RU','俄罗斯',61,98,'俄罗斯|俄羅斯|russia|🇷🇺'),('AU','澳大利亚',-25,134,'澳大利亚|澳洲|australia|🇦🇺'),('BR','巴西',-14,-52,'巴西|brazil|🇧🇷'),('MX','墨西哥',24,-102,'墨西哥|mexico|🇲🇽'),('ID','印度尼西亚',-2,118,'印度尼西亚|印尼|indonesia|🇮🇩')]


def infer_location(name):
    # Specific cities precede generic countries. Longer aliases win (e.g. Frankfurt vs Germany).
    matches=[(len(m.group()),row) for row in ROWS if (m:=re.search(row[6],name,re.I))]
    if matches:
        row=max(matches,key=lambda item:item[0])[1]
        return {**PLACES[row[0]],'source':'name','precision':'label'}
    for code,label,lat,lon,pattern in COUNTRIES:
        if re.search(pattern,name,re.I):
            return {'label':label,'country_code':code,'lat':lat,'lon':lon,'timezone':None,'source':'name','precision':'country'}
    return None


def zone_offsets(zone):
    tz=ZoneInfo(zone)
    def offset(month):
        minutes=int(datetime(datetime.now().year,month,15,tzinfo=tz).utcoffset().total_seconds()/60)
        return f"UTC{'+' if minutes>=0 else '−'}{abs(minutes)//60:02}:{abs(minutes)%60:02}"
    return {'january':offset(1),'july':offset(7)}


def validate_location(data):
    try:
        lat,lon=float(data['lat']),float(data['lon'])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:raise ValueError()
        zone=data['timezone'];ZoneInfo(zone)
        code=data['country_code'];label=data['label']
        if not isinstance(code,str) or not re.fullmatch('[A-Z]{2}',code):raise ValueError()
        if not isinstance(label,str) or not label.strip() or len(label)>120 or any(ord(c)<32 for c in label):raise ValueError()
        source=data.get('source','exit')
        if source not in ('exit','manual','name'):raise ValueError()
    except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):
        raise ValueError('位置信息或 IANA 时区不正确。')
    return {'label':label.strip(),'country_code':code,'lat':lat,'lon':lon,'timezone':zone,'source':source,'precision':data.get('precision','city'),'checked_at':data.get('checked_at',time.time()),**zone_offsets(zone)}


def node_location(store,node_id,name):
    saved=store.get_setting('node_location:'+node_id)
    if saved:
        try:return validate_location(saved)
        except ValueError:pass
    geo=infer_location(name)
    if geo and geo['timezone']:geo.update(zone_offsets(geo['timezone']))
    return geo


PROBE_SCRIPT=r'''
import httpx,json,subprocess,time,socket
p=subprocess.Popen(['mihomo','-f','/config/proxy.yaml'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(50):
  try:
   with socket.create_connection(('127.0.0.1',7890),timeout=.2):break
  except OSError:time.sleep(.1)
 with httpx.Client(proxy='http://127.0.0.1:7890',trust_env=False,timeout=15) as c:
  r=c.get('https://ipwho.is/?fields=success,country_code,city,latitude,longitude,timezone.id')
  r.raise_for_status();d=r.json()
  if not d.get('success'):raise ValueError()
  print(json.dumps({'country_code':d['country_code'],'label':d.get('city') or d['country_code'],'lat':d['latitude'],'lon':d['longitude'],'timezone':d['timezone']['id'],'source':'exit'}))
except Exception:print('{}')
finally:p.terminate();p.wait(timeout=3)
'''


class Geography:
    def __init__(self,store,runtime):
        self.store,self.runtime=store,runtime
        self.lock=threading.RLock();self.batch=None
        self.progress={'running':False,'done':0,'total':0,'failed':0}

    def locate(self,node_id,force=False):
        node=self.store.get_node(node_id)
        geo=node_location(self.store,node_id,node['name'])
        if geo and (geo['source']=='manual' or (geo['source']=='exit' and not force)):
            return geo
        from .runtime import IMAGE,build_proxy_config
        import yaml
        from pathlib import Path
        name='workbench-geo-'+uuid.uuid4().hex[:16]
        try:
            with tempfile.TemporaryDirectory(prefix='location-',dir=self.store.data_dir) as temp:
                file=Path(temp)/'proxy.yaml';file.write_text(yaml.safe_dump(build_proxy_config(node)));file.chmod(0o600)
                result=self.runtime._run(['run','--rm','--name',name,'--label','workbench.location-probe=true','--memory','256m','--cpus','0.5','--pids-limit','64','--security-opt','no-new-privileges:true','--mount',f'type=bind,source={temp},target=/config,readonly','--entrypoint','python',IMAGE,'-c',PROBE_SCRIPT],timeout=30,check=False)
                if result.returncode:raise ValueError()
                verified=validate_location(json.loads(result.stdout.strip()))
                self.store.set_setting('node_location:'+node_id,verified)
                return verified
        except Exception:
            if geo and geo.get('timezone'):return geo
            raise ValueError('节点位置未能检测，请在“订阅与线路”中为该节点手动选择城市。')
        finally:
            try:self.runtime._run(['rm','-f',name],timeout=5,check=False)
            except Exception:pass

    def start_batch(self):
        with self.lock:
            if self.batch and self.batch.is_alive():return
            nodes=[n for n in self.store.public_state()['nodes'] if not re.search('流量|到期|剩余|剩餘|续费|續費|更新时间|更新時間|续约|續約|expire|traffic',n['name'],re.I)][:100]
            self.progress={'running':True,'done':0,'total':len(nodes),'failed':0}
            self.batch=threading.Thread(target=self._batch,args=(nodes,),daemon=True);self.batch.start()

    def _batch(self,nodes):
        from concurrent.futures import ThreadPoolExecutor,as_completed
        def probe(node):
            try:
                value=self.locate(node['id'],force=True)
                return value['source'] in ('exit','manual')
            except Exception:return False
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                for task in as_completed([pool.submit(probe,node) for node in nodes]):
                    with self.lock:
                        self.progress['done']+=1
                        if not task.result():self.progress['failed']+=1
        finally:
            self.progress['running']=False
