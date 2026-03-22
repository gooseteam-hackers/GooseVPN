#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re, sys, asyncio, aiohttp, argparse, maxminddb, base64, json, random, os, hashlib, time
from urllib.parse import unquote, urlparse, parse_qs, unquote_plus
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from collections import defaultdict

INSECURE_PATTERN = re.compile(
    r'(?:[?&;]|3%[Bb])(allowinsecure|allow_insecure|insecure)=(?:1|true|yes)(?:[&;#]|$|(?=\s|$))',
    re.IGNORECASE
)

def is_insecure(url: str) -> bool:
    try:
        decoded = unquote_plus(unquote(url))
        return bool(INSECURE_PATTERN.search(decoded))
    except: return False

def filter_insecure(configs: List[str]) -> List[str]:
    return [c for c in configs if not is_insecure(c)]

COUNTRY_FLAGS = {
    'Россия': '🇷🇺', 'RU': '🇷🇺', 'Турция': '🇹🇷', 'TR': '🇹🇷',
    'Германия': '🇩🇪', 'DE': '🇩🇪', 'Нидерланды': '🇳🇱', 'NL': '🇳🇱',
    'Франция': '🇫🇷', 'FR': '🇫🇷', 'Великобритания': '🇬🇧', 'GB': '🇬🇧',
    'США': '🇺🇸', 'US': '🇺🇸', 'Япония': '🇯🇵', 'JP': '🇯🇵',
    'Корея': '🇰🇷', 'KR': '🇰🇷', 'Сингапур': '🇸🇬', 'SG': '🇸🇬',
    'Индия': '🇮🇳', 'IN': '🇮🇳', 'Грузия': '🇬🇪', 'GE': '🇬🇪',
    'Казахстан': '🇰🇿', 'KZ': '🇰🇿', 'Финляндия': '🇫🇮', 'FI': '🇫🇮',
    'Польша': '🇵🇱', 'PL': '🇵🇱', 'Украина': '🇺🇦', 'UA': '🇺🇦',
    'Global': '🌐',
}

def get_flag(country: str) -> str:
    if not country: return '🌐'
    country = country.strip()
    if country in COUNTRY_FLAGS: return COUNTRY_FLAGS[country]
    if country.upper() in COUNTRY_FLAGS: return COUNTRY_FLAGS[country.upper()]
    for key, flag in COUNTRY_FLAGS.items():
        if key.lower() in country.lower() or country.lower() in key.lower():
            return flag
    return '🌐'

class ConfigType(Enum):
    WLTE = auto()
    WIFI = auto()
    WARP_STABLE = auto()
    WARP_NIGHT = auto()
    RESERVE = auto()

@dataclass
class VPNConfig:
    url: str
    config_type: ConfigType
    country: str
    original_name: str
    ip: Optional[str] = None
    ping_ms: Optional[float] = None
    speed_score: float = 0.0
    rank: Optional[int] = None
    stability_score: float = 0.0
    
    @property
    def flag(self) -> str:
        if self.config_type in [ConfigType.WARP_STABLE, ConfigType.WARP_NIGHT]:
            return '🔥'
        return get_flag(self.country)
    
    @property
    def type_label(self) -> str:
        return {
            ConfigType.WLTE: 'wLTE', ConfigType.WIFI: 'WiFi',
            ConfigType.WARP_STABLE: 'WARP', ConfigType.WARP_NIGHT: 'WARP',
            ConfigType.RESERVE: 'Резерв',
        }.get(self.config_type, 'Unknown')
    
    @property
    def warp_mode(self) -> Optional[str]:
        if self.config_type == ConfigType.WARP_STABLE: return 'Стабильный'
        if self.config_type == ConfigType.WARP_NIGHT: return 'Ночной'
        return None
    
    def format_name(self) -> str:
        if self.config_type == ConfigType.RESERVE:
            base = f"🪿 [{self.type_label}] Резерв"
            if self.rank: base += f" {self.rank}"
            return base
        if self.config_type in [ConfigType.WARP_STABLE, ConfigType.WARP_NIGHT]:
            base = f"🔥 [WARP]"
            if self.warp_mode: base += f" {self.warp_mode}"
            if self.rank: base += f" {self.rank}"
            return base
        base = f"{self.flag} [{self.type_label}] {self.country}"
        if self.rank: base += f" {self.rank}"
        return base
    
    def to_subscription_line(self) -> str:
        name = unquote(self.format_name())
        if '#' in self.url:
            parts = self.url.rsplit('#', 1)
            return f"{parts[0]}#{name}"
        return f"{self.url}#{name}"
    
    def composite_score(self) -> float:
        """Комбинированный скор: пинг + стабильность"""
        ping_score = max(0, 100 - (self.ping_ms or 999))
        return ping_score * 0.7 + self.stability_score * 0.3

class GeoLocator:
    GEO_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
    
    def __init__(self, db_path: Optional[str] = None, auto_cleanup: bool = True):
        self.reader = None
        self.cache = {}
        self.downloaded_path: Optional[Path] = None
        self.auto_cleanup = auto_cleanup
        paths = [db_path, "./GeoLite2-Country.mmdb", "./configs/GeoLite2-Country.mmdb", "/usr/share/GeoIP/GeoLite2-Country.mmdb"]
        for path in paths:
            if path and Path(path).exists():
                try:
                    self.reader = maxminddb.open_database(path)
                    return
                except: pass
        self._download_db()
    
    def _download_db(self):
        try:
            import urllib.request
            self.downloaded_path = Path("./configs/GeoLite2-Country.mmdb")
            self.downloaded_path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(self.GEO_URL, self.downloaded_path)
            if self.downloaded_path.exists() and self.downloaded_path.stat().st_size > 10000:
                self.reader = maxminddb.open_database(self.downloaded_path)
        except: pass
    
    def get_country_by_ip(self, ip: str) -> Optional[str]:
        if ip and any(ip.startswith(p) for p in ['10.','192.168.','172.16.','172.17.','172.18.','172.19.','172.2','172.30.','172.31.','127.','0.0.0.0']):
            return None
        if ip in self.cache: return self.cache[ip]
        if not self.reader or not ip: return None
        try:
            result = self.reader.get(ip)
            if result:
                names = result.get('country', {}).get('names', {})
                country = names.get('ru') or names.get('en')
                self.cache[ip] = country
                return country
        except: pass
        return None
    
    def close(self):
        if self.reader: self.reader.close()
        if self.auto_cleanup and self.downloaded_path and self.downloaded_path.exists():
            try: self.downloaded_path.unlink()
            except: pass

class ConfigParser:
    @staticmethod
    def extract_country(name: str) -> str:
        clean = re.sub(r'[^\w\s\u0400-\u04FF\u00C0-\u024F-]', ' ', name)
        for country in ['Россия','Турция','Германия','Нидерланды','Франция','США','Великобритания','Япония','Корея','Сингапур','Индия','Грузия','Казахстан']:
            if country.lower() in clean.lower(): return country
        return 'Unknown'
    
    @classmethod
    def _extract_host(cls, url: str) -> Optional[str]:
        try:
            rest = url.replace('vless://', '').split('#')[0]
            if '@' in rest:
                _, hp = rest.split('@', 1)
                host = hp.split(':')[0].split('?')[0]
                if host and len(host) > 3: return host
        except: pass
        return None
    
    @classmethod
    def parse_vless(cls, url: str, ctype: ConfigType, geo: Optional[GeoLocator] = None) -> Optional[VPNConfig]:
        try:
            rest = url.replace('vless://', '', 1)
            name = unquote(rest.rsplit('#', 1)[1]) if '#' in rest else "Unnamed"
            host = cls._extract_host(url)
            country = cls.extract_country(name)
            if country == 'Unknown' and host and geo:
                detected = geo.get_country_by_ip(host)
                if detected: country = detected
            return VPNConfig(url=url, config_type=ctype, country=country if country != 'Unknown' else 'Global', original_name=name, ip=host)
        except: return None
    
    @classmethod
    def parse_warp(cls, url: str, ctype: ConfigType) -> Optional[VPNConfig]:
        return VPNConfig(url=url, config_type=ctype, country='Cloudflare', original_name='WARP')

SOURCES_WLTE = [
    "https://wlrus.lol/confs/selected.txt",
    "https://raw.githubusercontent.com/sakha1370/OpenRay/refs/heads/main/output/all_valid_proxies.txt",
    "https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt",
    "https://raw.githubusercontent.com/yitong2333/proxy-minging/refs/heads/main/v2ray.txt",
    "https://raw.githubusercontent.com/acymz/AutoVPN/refs/heads/main/data/V2.txt",
    "https://raw.githubusercontent.com/miladtahanian/V2RayCFGDumper/refs/heads/main/sub.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt",
    "https://raw.githubusercontent.com/CidVpn/cid-vpn-config/refs/heads/main/general.txt",
    "https://raw.githubusercontent.com/mohamadfg-dev/telegram-v2ray-configs-collector/refs/heads/main/category/vless.txt",
    "https://raw.githubusercontent.com/mheidari98/.proxy/refs/heads/main/vless",
    "https://raw.githubusercontent.com/youfoundamin/V2rayCollector/main/mixed_iran.txt",
    "https://raw.githubusercontent.com/expressalaki/ExpressVPN/refs/heads/main/configs3.txt",
    "https://raw.githubusercontent.com/MahsaNetConfigTopic/config/refs/heads/main/xray_final.txt",
    "https://raw.githubusercontent.com/miladtahanian/Config-Collector/refs/heads/main/mixed_iran.txt",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/refs/heads/main/sub",
    "https://raw.githubusercontent.com/free18/v2ray/refs/heads/main/v.txt",
]

SOURCES_WIFI = [
    "https://wlrus.lol/confs/blackl.txt",
    "https://github.com/Epodonios/v2ray-configs/raw/main/Splitted-By-Protocol/trojan.txt",
    "https://raw.githubusercontent.com/shabane/kamaji/master/hub/merged.txt",
    "https://raw.githubusercontent.com/wuqb2i4f/xray-config-toolkit/main/output/base64/mix-uri",
    "https://raw.githubusercontent.com/WhitePrime/xraycheck/refs/heads/main/configs/available",
    "https://raw.githubusercontent.com/STR97/STRUGOV/refs/heads/main/STR.BYPASS",
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/refs/heads/main/Config/vless.txt",
]

WARP_STABLE = "warp://162.159.192.79:3476?ifp=10-20&ifps=20-60&ifpd=5-10&ifpm=m4#Cloud-#1&&detour=warp://162.159.195.203:8319?ifp=10-20&ifps=20-60&ifpd=5-10#Cloud-#2"
WARP_NIGHT_URL = "https://raw.githubusercontent.com/ByteMysticRogue/Hiddify-Warp/refs/heads/main/warp.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
    "v2RayTun/1.5.0 (Android; 13)",
    "okhttp/4.12.0",
]

class PingCache:
    def __init__(self, cache_file: str = "configs/ping_cache.json", ttl_hours: int = 24):
        self.cache_file = Path(cache_file)
        self.ttl = timedelta(hours=ttl_hours)
        self.data = self._load()
    
    def _load(self) -> Dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except: pass
        return {}
    
    def get(self, ip: str) -> Optional[float]:
        if ip not in self.data: return None
        cached = self.data[ip]
        if datetime.now() - datetime.fromisoformat(cached['t']) < self.ttl:
            return cached['p']
        return None
    
    def set(self, ip: str, ping: float):
        self.data[ip] = {'p': ping, 't': datetime.now().isoformat()}
        self._save()
    
    def _save(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except: pass

class FunnelPingTester:
    """Трёхступенчатая воронка пинг-тестов"""
    
    STAGES = [
        {'name': '🔍 Скрининг', 'concurrent': 50, 'timeout': 1.0, 'keep_ratio': 0.04},  # 4% → топ-200
        {'name': '⚡ Средний тест', 'concurrent': 30, 'timeout': 2.0, 'keep_ratio': 0.25},  # 25% → топ-50
        {'name': '🏆 Финал', 'concurrent': 15, 'timeout': 3.0, 'keep_ratio': 1.0},  # 100% → топ-8
    ]
    
    def __init__(self, cache: PingCache = None):
        self.cache = cache or PingCache()
    
    async def _single_test(self, session: aiohttp.ClientSession, host: str, timeout: float) -> Optional[float]:
        try:
            for scheme in ['https', 'http']:
                try:
                    start = asyncio.get_event_loop().time()
                    async with session.get(f"{scheme}://{host}:443/", timeout=timeout, allow_redirects=False):
                        return round((asyncio.get_event_loop().time() - start) * 1000, 1)
                except: continue
        except: pass
        return None
    
    async def _test_batch(self, configs: List[VPNConfig], concurrent: int, timeout: float) -> List[VPNConfig]:
        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(concurrent)
            async def test_one(cfg: VPNConfig):
                async with sem:
                    if cfg.ip:
                        cached = self.cache.get(cfg.ip) if self.cache else None
                        if cached:
                            cfg.ping_ms = cached
                        else:
                            ping = await self._single_test(session, cfg.ip, timeout)
                            if ping:
                                cfg.ping_ms = ping
                                if self.cache: self.cache.set(cfg.ip, ping)
                    cfg.speed_score = max(0, 100 - (cfg.ping_ms or 999))
                    cfg.stability_score = random.uniform(0.8, 1.0) if cfg.ping_ms else 0
                return cfg
            return await asyncio.gather(*(test_one(c) for c in configs))
    
    async def run_funnel(self, configs: List[VPNConfig], final_count: int = 8) -> List[VPNConfig]:
        """Запускает трёхступенчатую воронку"""
        current = configs.copy()
        print(f"🚀 Запуск воронки: {len(current)} конфигов")
        
        for i, stage in enumerate(self.STAGES[:-1], 1):
            if not current: break
            print(f"  {stage['name']}: {len(current)} → {int(len(current)*stage['keep_ratio'])}")
            tested = await self._test_batch(current, stage['concurrent'], stage['timeout'])
            tested.sort(key=lambda x: x.composite_score(), reverse=True)
            keep_count = max(int(len(tested) * stage['keep_ratio']), final_count * 2)
            current = tested[:keep_count]
            await asyncio.sleep(0.5) 
        
        final_stage = self.STAGES[-1]
        print(f"  {final_stage['name']}: {len(current)} → {final_count}")
        final_tested = await self._test_batch(current, final_stage['concurrent'], final_stage['timeout'])
        final_tested.sort(key=lambda x: x.composite_score(), reverse=True)
        return final_tested[:final_count]

class DataSource:
    async def fetch(self, session: aiohttp.ClientSession, **kw) -> List[str]: raise NotImplementedError

class TxtSource(DataSource):
    def __init__(self, url: str): self.url = url
    async def fetch(self, session: aiohttp.ClientSession, **kw) -> List[str]:
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            async with session.get(self.url, timeout=15, headers=headers) as r:
                text = await r.text()
                lines = [l.strip() for l in text.split('\n') if l.strip().startswith('vless://')]
                return filter_insecure(lines)
        except: return []

class WarpSource(DataSource):
    async def fetch(self, session: aiohttp.ClientSession, **kw) -> List[VPNConfig]:
        configs = []
        if c := ConfigParser.parse_warp(WARP_STABLE, ConfigType.WARP_STABLE): configs.append(c)
        try:
            async with session.get(WARP_NIGHT_URL, timeout=10) as r:
                text = await r.text()
                for line in reversed([l.strip() for l in text.split('\n') if l.strip() and not l.startswith('//')]):
                    if line.startswith('warp://') and (c := ConfigParser.parse_warp(line, ConfigType.WARP_NIGHT)):
                        configs.append(c); break
        except: pass
        return configs

class ConfigFilter:
    def __init__(self, main_wlte: int, main_wifi: int, reserve_wlte: int, reserve_wifi: int):
        self.main_wlte, self.main_wifi = main_wlte, main_wifi
        self.reserve_wlte, self.reserve_wifi = reserve_wlte, reserve_wifi
    
    def select(self, configs: List[VPNConfig]) -> Tuple[List[VPNConfig], List[VPNConfig]]:
        wlte = [c for c in configs if c.config_type == ConfigType.WLTE]
        wifi = [c for c in configs if c.config_type == ConfigType.WIFI]
        wlte.sort(key=lambda x: x.composite_score(), reverse=True)
        wifi.sort(key=lambda x: x.composite_score(), reverse=True)
        main, reserves = [], []
        for rank, c in enumerate(wlte[:self.main_wlte], 1): c.rank = rank; main.append(c)
        for rank, c in enumerate(wifi[:self.main_wifi], 1): c.rank = rank; main.append(c)
        reserve_rank = 1
        for c in wlte[self.main_wlte:self.main_wlte + self.reserve_wlte]:
            c.rank = reserve_rank; c.config_type = ConfigType.RESERVE; reserves.append(c); reserve_rank += 1
        for c in wifi[self.main_wifi:self.main_wifi + self.reserve_wifi]:
            c.rank = reserve_rank; c.config_type = ConfigType.RESERVE; reserves.append(c); reserve_rank += 1
        return main, reserves

class SubscriptionGenerator:
    HEADERS_BASE = [
        "//profile-update-interval: 24",
        "//subscription-userinfo: upload=0; download=0; total=10737418240000000; expire=2546249531",
    ]
    TITLE_BALANCED = base64.b64encode("🪿 GooseVPN".encode()).decode()
    TITLE_PLUS = base64.b64encode("🪿 GooseVPN Plus".encode()).decode()
    
    @classmethod
    def generate(cls, main: List[VPNConfig], reserves: List[VPNConfig], output: str, title: str, include_warp: bool = True, warp_configs: List = None, is_plus: bool = False):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        all_cfgs = main + reserves
        if include_warp and warp_configs: all_cfgs.extend(warp_configs)
        stats = {'total': len(all_cfgs), 'wlte': len([c for c in all_cfgs if c.config_type == ConfigType.WLTE]), 'wifi': len([c for c in all_cfgs if c.config_type == ConfigType.WIFI]), 'reserve': len([c for c in all_cfgs if c.config_type == ConfigType.RESERVE])}
        with open(output, 'w', encoding='utf-8') as f:
            f.write(f"//profile-title: base64:{cls.TITLE_PLUS if is_plus else cls.TITLE_BALANCED}\n")
            for h in cls.HEADERS_BASE: f.write(h + '\n')
            f.write(f"//last update on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            warp_note = ", ночной и стабильный WARP" if include_warp else ""
            f.write(f"// 🪿 {title} - {stats['total']} конфигов, {stats['wlte']} wLTE, {stats['wifi']} WiFi, {stats['reserve']} резервов{warp_note}\n\n")
            sections = [(ConfigType.WLTE,'wLTE'), (ConfigType.WIFI,'WiFi'), (ConfigType.RESERVE,'Резерв')]
            if include_warp: sections += [(ConfigType.WARP_STABLE,'WARP Стабильный'), (ConfigType.WARP_NIGHT,'WARP Ночной')]
            for ctype, label in sections:
                group = sorted([c for c in all_cfgs if c.config_type == ctype], key=lambda x: x.rank or 99)
                if not group: continue
                f.write(f"// =-=-=-=-=-= {label} =-=-=-=-=-=\n")
                for cfg in group: f.write(cfg.to_subscription_line() + '\n')
                f.write('\n')
        print(f"✅ {title}: {output} ({stats['total']} конфигов)")

def parse_args():
    p = argparse.ArgumentParser(description="🪿 GooseVPN")
    p.add_argument('-o','--out', type=str, default='configs', help='Папка вывода')
    p.add_argument('--geo', type=str, help='Путь к GeoLite2')
    p.add_argument('--skip-funnel', action='store_true', help='Пропустить воронку, взять первые конфиги')
    p.add_argument('--only-balanced', action='store_true', help='Только balanced.txt')
    p.add_argument('--only-plus', action='store_true', help='Только plus.txt')
    return p.parse_args()

async def main_async(args):
    print("🪿 GooseVPN")
    geo = GeoLocator(args.geo, auto_cleanup=True)
    cache = PingCache()
    
    async with aiohttp.ClientSession() as session:
        wlte_raw, wifi_raw = [], []
        for src in SOURCES_WLTE:
            data = await TxtSource(src).fetch(session)
            wlte_raw.extend(data)
        for src in SOURCES_WIFI:
            data = await TxtSource(src).fetch(session)
            wifi_raw.extend(data)
        
        print(f"📥 Собрано: {len(wlte_raw)} wLTE + {len(wifi_raw)} WiFi")
        
        wlte_cfgs = [c for url in wlte_raw if (c := ConfigParser.parse_vless(url, ConfigType.WLTE, geo))]
        wifi_cfgs = [c for url in wifi_raw if (c := ConfigParser.parse_vless(url, ConfigType.WIFI, geo))]
        warp_cfgs = await WarpSource().fetch(session)
        
        all_cfgs = wlte_cfgs + wifi_cfgs
        print(f"🔍 После парсинга: {len(all_cfgs)} валидных конфигов")
        
        if not args.skip_funnel and all_cfgs:
            tester = FunnelPingTester(cache)
            best_wlte = await tester.run_funnel([c for c in all_cfgs if c.config_type == ConfigType.WLTE], final_count=8)
            best_wifi = await tester.run_funnel([c for c in all_cfgs if c.config_type == ConfigType.WIFI], final_count=8)
            selected = best_wlte + best_wifi
            print(f"🏆 После воронки: {len(selected)} лучших конфигов")
        else:
            all_cfgs.sort(key=lambda x: x.speed_score, reverse=True)
            selected = all_cfgs[:16]
            print(f"⚡ Быстрый отбор: {len(selected)} конфигов")
        
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        
        if not args.only_plus:
            filter_b = ConfigFilter(main_wlte=3, main_wifi=3, reserve_wlte=1, reserve_wifi=2)
            main_b, reserves_b = filter_b.select(selected)
            SubscriptionGenerator.generate(main_b, reserves_b, out_dir / "balanced.txt", "GooseVPN 🪿", include_warp=False, is_plus=False)
        
        if not args.only_balanced:
            filter_p = ConfigFilter(main_wlte=4, main_wifi=4, reserve_wlte=2, reserve_wifi=2)
            main_p, reserves_p = filter_p.select(selected)
            SubscriptionGenerator.generate(main_p, reserves_p, out_dir / "plus.txt", "GooseVPN Plus 🪿", include_warp=True, warp_configs=warp_cfgs, is_plus=True)
    
    cache._save()  
    geo.close()
    print("✨ Готово!")

def main():
    args = parse_args()
    try: asyncio.run(main_async(args))
    except KeyboardInterrupt: print("\n👋 Прервано")
    except Exception as e:
        print(f"❌ {e}")
        if '-v' in sys.argv: import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
