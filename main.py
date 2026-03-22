#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re, sys, asyncio, aiohttp, argparse, maxminddb, base64, json, random
from urllib.parse import unquote, urlparse, parse_qs, unquote_plus
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from collections import defaultdict
import threading

INSECURE_PATTERN = re.compile(
    r'(?:[?&;]|3%[Bb])(allowinsecure|allow_insecure|insecure)=(?:1|true|yes)(?:[&;#]|$|(?=\s|$))',
    re.IGNORECASE
)

def is_insecure(url: str) -> bool:
    """Проверяет конфиг на наличие allowInsecure=true"""
    try:
        decoded = unquote_plus(unquote(url))
        return bool(INSECURE_PATTERN.search(decoded))
    except:
        return False

def filter_insecure(configs: list[str]) -> list[str]:
    """Фильтрует небезопасные конфиги"""
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
    "https://wlrus.lol/confs/selected.txt",  # Лучший
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
    "https://wlrus.lol/confs/blackl.txt",  # Лучший
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

class DataSource:
    async def fetch(self, session: aiohttp.ClientSession, **kw) -> list[str]: raise NotImplementedError

class TxtSource(DataSource):
    def __init__(self, url: str): self.url = url
    async def fetch(self, session: aiohttp.ClientSession, **kw) -> list[str]:
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            async with session.get(self.url, timeout=15, headers=headers) as r:
                text = await r.text()
                lines = [l.strip() for l in text.split('\n') if l.strip().startswith('vless://')]
                return filter_insecure(lines)
        except: return []

class WarpSource(DataSource):
    async def fetch(self, session: aiohttp.ClientSession, **kw) -> list[VPNConfig]:
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

class PingTester:
    TIMEOUT = 3
    @staticmethod
    async def test_host(session: aiohttp.ClientSession, host: str, port: int = 443) -> Optional[float]:
        try:
            for scheme in ['https','http']:
                try:
                    start = asyncio.get_event_loop().time()
                    async with session.get(f"{scheme}://{host}:{port}/", timeout=PingTester.TIMEOUT, allow_redirects=False):
                        return round((asyncio.get_event_loop().time() - start) * 1000, 1)
                except: continue
        except: pass
        return None
    
    @classmethod
    async def test_configs(cls, configs: list[VPNConfig], max_concurrent: int = 20) -> list[VPNConfig]:
        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(max_concurrent)
            async def test(cfg: VPNConfig):
                async with sem:
                    if cfg.ip and (ping := await cls.test_host(session, cfg.ip)):
                        cfg.ping_ms, cfg.speed_score = ping, max(0, 100 - ping)
                    else:
                        cfg.speed_score = sum(ord(c) for c in cfg.original_name) % 100
                return cfg
            return await asyncio.gather(*(test(c) for c in configs))

class ConfigFilter:
    def __init__(self, main_wlte: int, main_wifi: int, reserve_wlte: int, reserve_wifi: int):
        self.main_wlte, self.main_wifi = main_wlte, main_wifi
        self.reserve_wlte, self.reserve_wifi = reserve_wlte, reserve_wifi
    
    def select(self, configs: list[VPNConfig]) -> tuple[list[VPNConfig], list[VPNConfig]]:
        wlte = [c for c in configs if c.config_type == ConfigType.WLTE]
        wifi = [c for c in configs if c.config_type == ConfigType.WIFI]
        wlte.sort(key=lambda x: (x.ping_ms if x.ping_ms else 9999, -x.speed_score))
        wifi.sort(key=lambda x: (x.ping_ms if x.ping_ms else 9999, -x.speed_score))
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
    def generate(cls, main: list[VPNConfig], reserves: list[VPNConfig], output: str, title: str, include_warp: bool = True, warp_configs: list = None, is_plus: bool = False):
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
    p = argparse.ArgumentParser(description="🪿 GooseVPN Parser v2.0")
    p.add_argument('-o','--out', type=str, default='configs', help='Папка вывода')
    p.add_argument('--geo', type=str, help='Путь к GeoLite2')
    p.add_argument('--no-ping', action='store_true', help='Без пинг-тестов')
    p.add_argument('--ping-n', type=int, default=20, help='Параллельных пингов')
    p.add_argument('--only-balanced', action='store_true', help='Только balanced.txt')
    p.add_argument('--only-plus', action='store_true', help='Только plus.txt')
    return p.parse_args()

async def main_async(args):
    print("🪿 GooseVPN Parser v2.0 — новые источники + wlrus.lol приоритет")
    geo = GeoLocator(args.geo, auto_cleanup=True)
    
    async with aiohttp.ClientSession() as session:
        wlte_raw = []
        for src in SOURCES_WLTE:
            data = await TxtSource(src).fetch(session)
            wlte_raw.extend(data)
            print(f"📥 wLTE: {src.split('/')[-1]} → {len(data)}")
        
        wifi_raw = []
        for src in SOURCES_WIFI:
            data = await TxtSource(src).fetch(session)
            wifi_raw.extend(data)
            print(f"📥 WiFi: {src.split('/')[-1]} → {len(data)}")
        
        wlte_cfgs = [c for url in wlte_raw if (c := ConfigParser.parse_vless(url, ConfigType.WLTE, geo))]
        wifi_cfgs = [c for url in wifi_raw if (c := ConfigParser.parse_vless(url, ConfigType.WIFI, geo))]
        
        warp_cfgs = await WarpSource().fetch(session)
        
        all_cfgs = wlte_cfgs + wifi_cfgs
        
        if not args.no_ping and all_cfgs:
            print(f"⚡ Пинг-тест ({args.ping_n} параллельно)...")
            all_cfgs = await PingTester.test_configs(all_cfgs, args.ping_n)
        
        non_warp = [c for c in all_cfgs if c.config_type not in [ConfigType.WARP_STABLE, ConfigType.WARP_NIGHT]]
        
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        
        if not args.only_plus:
            filter_b = ConfigFilter(main_wlte=3, main_wifi=3, reserve_wlte=1, reserve_wifi=2)
            main_b, reserves_b = filter_b.select(non_warp)
            SubscriptionGenerator.generate(main_b, reserves_b, out_dir / "balanced.txt", "GooseVPN 🪿", include_warp=False, is_plus=False)
        
        if not args.only_balanced:
            filter_p = ConfigFilter(main_wlte=4, main_wifi=4, reserve_wlte=2, reserve_wifi=2)
            main_p, reserves_p = filter_p.select(non_warp)
            SubscriptionGenerator.generate(main_p, reserves_p, out_dir / "plus.txt", "GooseVPN Plus 🪿", include_warp=True, warp_configs=warp_cfgs, is_plus=True)
    
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
