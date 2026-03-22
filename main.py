#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re, sys, asyncio, aiohttp, argparse, maxminddb, base64, json, random, os, socket
from urllib.parse import unquote, urlparse, parse_qs, unquote_plus
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from functools import lru_cache
import html

@lru_cache(maxsize=1024)
def cached_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return socket.getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        return []

socket.getaddrinfo = cached_getaddrinfo

INSECURE_PATTERN = re.compile(r'(?:[?&;]|3%[Bb])(allowinsecure|allow_insecure|insecure)=(?:1|true|yes)(?:[&;#]|$|(?=\s|$))', re.IGNORECASE)

def is_insecure(url: str) -> bool:
    try:
        decoded = unquote_plus(unquote(url))
        return bool(INSECURE_PATTERN.search(decoded))
    except:
        return False

def filter_insecure(configs: List[str]) -> List[str]:
    return [c for c in configs if not is_insecure(c)]

def try_decode_base64(text: str) -> str:
    try:
        text = text.strip()
        if len(text) % 4:
            text += '=' * (4 - len(text) % 4)
        decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
        if decoded.startswith(('vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://')):
            return decoded
    except:
        pass
    return text

def extract_configs_from_text(text: str) -> List[str]:
    configs = []
    text = unquote_plus(html.unescape(text))
    
    # Пробуем декодировать весь текст как base64 (если это подписка)
    if not text.startswith(('vless://', 'vmess://', 'trojan://', 'ss://')):
        decoded = try_decode_base64(text.split('\n')[0].strip())
        if decoded != text.split('\n')[0].strip():
            text = decoded
    
    # Разделяем на строки и ищем конфиги
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Ищем протоколы в строке
        for proto in ['vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://', 'tuic://', 'hysteria://', 'hysteria2://']:
            if proto in line:
                # Извлекаем конфиг начиная с протокола
                start = line.find(proto)
                config = line[start:].split()[0]  # Берём до первого пробела
                config = config.rstrip('\x00')  # Убираем null-символы
                if not is_insecure(config):
                    configs.append(config)
                break
    
    return configs

COUNTRY_FLAGS = {
    'Россия': '🇷🇺', 'RU': '🇷🇺', 'Турция': '🇹🇷', 'TR': '🇹🇷',
    'Германия': '🇩🇪', 'DE': '🇩🇪', 'Нидерланды': '🇳🇱', 'NL': '🇳🇱',
    'Франция': '🇫🇷', 'FR': '🇫🇷', 'Великобритания': '🇬🇧', 'GB': '🇬🇧',
    'США': '🇺🇸', 'US': '🇺🇸', 'Япония': '🇯🇵', 'JP': '🇯🇵',
    'Корея': '🇰🇷', 'KR': '🇰🇷', 'Сингапур': '🇸🇬', 'SG': '🇸🇬',
    'Индия': '🇮🇳', 'IN': '🇮🇳', 'Грузия': '🇬🇪', 'GE': '🇬🇪',
    'Казахстан': '🇰🇿', 'KZ': '🇰🇿', 'Global': '🌐',
}

def get_flag(country: str) -> str:
    if not country:
        return '🌐'
    country = country.strip()
    if country in COUNTRY_FLAGS:
        return COUNTRY_FLAGS[country]
    if country.upper() in COUNTRY_FLAGS:
        return COUNTRY_FLAGS[country.upper()]
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
            ConfigType.WLTE: 'wLTE',
            ConfigType.WIFI: 'WiFi',
            ConfigType.WARP_STABLE: 'WARP',
            ConfigType.WARP_NIGHT: 'WARP',
            ConfigType.RESERVE: 'Резерв',
        }.get(self.config_type, 'Unknown')

    @property
    def warp_mode(self) -> Optional[str]:
        if self.config_type == ConfigType.WARP_STABLE:
            return 'Стабильный'
        if self.config_type == ConfigType.WARP_NIGHT:
            return 'Ночной'
        return None

    def format_name(self) -> str:
        if self.config_type == ConfigType.RESERVE:
            base = f"🪿 [{self.type_label}] Резерв"
            if self.rank:
                base += f" {self.rank}"
            return base
        if self.config_type in [ConfigType.WARP_STABLE, ConfigType.WARP_NIGHT]:
            base = f"🔥 [WARP]"
            if self.warp_mode:
                base += f" {self.warp_mode}"
            if self.rank:
                base += f" {self.rank}"
            return base
        base = f"{self.flag} [{self.type_label}] {self.country}"
        if self.rank:
            base += f" {self.rank}"
        return base

    def to_subscription_line(self) -> str:
        name = unquote(self.format_name())
        if '#' in self.url:
            parts = self.url.rsplit('#', 1)
            return f"{parts[0]}#{name}"
        return f"{self.url}#{name}"

    def composite_score(self) -> float:
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
                except:
                    pass
        self._download_db()

    def _download_db(self):
        try:
            import urllib.request
            self.downloaded_path = Path("./configs/GeoLite2-Country.mmdb")
            self.downloaded_path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(self.GEO_URL, self.downloaded_path)
            if self.downloaded_path.exists() and self.downloaded_path.stat().st_size > 10000:
                self.reader = maxminddb.open_database(self.downloaded_path)
        except:
            pass

    def get_country_by_ip(self, ip: str) -> Optional[str]:
        if ip and any(ip.startswith(p) for p in ['10.','192.168.','172.16.','172.17.','172.18.','172.19.','172.2','172.30.','172.31.','127.','0.0.0.0']):
            return None
        if ip in self.cache:
            return self.cache[ip]
        if not self.reader or not ip:
            return None
        try:
            result = self.reader.get(ip)
            if result:
                names = result.get('country', {}).get('names', {})
                country = names.get('ru') or names.get('en')
                self.cache[ip] = country
                return country
        except:
            pass
        return None

    def close(self):
        if self.reader:
            self.reader.close()
        if self.auto_cleanup and self.downloaded_path and self.downloaded_path.exists():
            try:
                self.downloaded_path.unlink()
            except:
                pass

class ConfigParser:
    @staticmethod
    def extract_country(name: str) -> str:
        clean = re.sub(r'[^\w\s\u0400-\u04FF\u00C0-\u024F-]', ' ', name)
        for country in ['Россия','Турция','Германия','Нидерланды','Франция','США','Великобритания','Япония','Корея','Сингапур','Индия','Грузия','Казахстан']:
            if country.lower() in clean.lower():
                return country
        return 'Unknown'

    @classmethod
    def _extract_host(cls, url: str) -> Optional[str]:
        try:
            rest = url.replace('vless://', '').replace('vmess://', '').replace('trojan://', '').split('#')[0]
            if '@' in rest:
                _, hp = rest.split('@', 1)
                host = hp.split(':')[0].split('?')[0]
                if host and len(host) > 3:
                    return host
        except:
            pass
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
                if detected:
                    country = detected
            return VPNConfig(url=url, config_type=ctype, country=country if country != 'Unknown' else 'Global', original_name=name, ip=host)
        except:
            return None

    @classmethod
    def parse_warp(cls, url: str, ctype: ConfigType) -> Optional[VPNConfig]:
        return VPNConfig(url=url, config_type=ctype, country='Cloudflare', original_name='WARP')

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
            except:
                pass
        return {}

    def get(self, ip: str) -> Optional[float]:
        if ip not in self.data:
            return None
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
        except:
            pass

class SourceFetcher:
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
        "v2RayTun/1.5.0 (Android; 13)",
        "okhttp/4.12.0",
    ]

    DEFAULT_WLTE_URLS = [
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

    DEFAULT_WIFI_URLS = [
        "https://wlrus.lol/confs/blackl.txt",
        "https://raw.githubusercontent.com/shabane/kamaji/master/hub/merged.txt",
        "https://raw.githubusercontent.com/wuqb2i4f/xray-config-toolkit/main/output/base64/mix-uri",
        "https://raw.githubusercontent.com/WhitePrime/xraycheck/refs/heads/main/configs/available",
        "https://raw.githubusercontent.com/STR97/STRUGOV/refs/heads/main/STR.BYPASS",
        "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/refs/heads/main/Config/vless.txt",
    ]

    def __init__(self, sources_file: str, ctype: ConfigType):
        self.sources_file = Path(sources_file)
        self.ctype = ctype

    def _load_urls(self) -> List[str]:
        urls = []
        if self.sources_file.exists():
            content = self.sources_file.read_text(encoding='utf-8')
            urls = [line.strip() for line in content.split('\n') if line.strip().startswith('http')]
        if not urls:
            print(f"⚠️ {self.sources_file} пустой, используем fallback URL")
            if self.ctype == ConfigType.WLTE:
                urls = self.DEFAULT_WLTE_URLS
            elif self.ctype == ConfigType.WIFI:
                urls = self.DEFAULT_WIFI_URLS
        else:
            print(f"✅ {self.sources_file}: {len(urls)} URL")
        return urls

    async def fetch_all(self, session: aiohttp.ClientSession, geo: Optional[GeoLocator] = None) -> List[VPNConfig]:
        urls = self._load_urls()
        if not urls:
            return []
        configs = []
        headers = {'User-Agent': random.choice(self.USER_AGENTS)}
        for url in urls:
            try:
                async with session.get(url, timeout=15, headers=headers) as r:
                    text = await r.text()
                    # Извлекаем конфиги из текста (base64, mixed protocols, etc.)
                    raw_configs = extract_configs_from_text(text)
                    for config in raw_configs:
                        if config.startswith('vless://'):
                            if c := ConfigParser.parse_vless(config, self.ctype, geo):
                                configs.append(c)
            except Exception as e:
                pass
        print(f"   📥 {self.ctype.name}: {len(configs)} конфигов")
        return configs

class WarpSource:
    WARP_STABLE = "warp://162.159.192.79:3476?ifp=10-20&ifps=20-60&ifpd=5-10&ifpm=m4#Cloud-#1&&detour=warp://162.159.195.203:8319?ifp=10-20&ifps=20-60&ifpd=5-10#Cloud-#2"
    WARP_NIGHT_URL = "https://raw.githubusercontent.com/ByteMysticRogue/Hiddify-Warp/refs/heads/main/warp.json"

    async def fetch(self, session: aiohttp.ClientSession) -> List[VPNConfig]:
        configs = []
        if c := ConfigParser.parse_warp(self.WARP_STABLE, ConfigType.WARP_STABLE):
            configs.append(c)
        try:
            async with session.get(self.WARP_NIGHT_URL, timeout=10) as r:
                text = await r.text()
                for line in reversed([l.strip() for l in text.split('\n') if l.strip() and not l.startswith('//')]):
                    if line.startswith('warp://') and (c := ConfigParser.parse_warp(line, ConfigType.WARP_NIGHT)):
                        configs.append(c)
                        break
        except:
            pass
        return configs

class ConfigFilter:
    def __init__(self, main_wlte: int, main_wifi: int, reserve_wlte: int, reserve_wifi: int):
        self.main_wlte = main_wlte
        self.main_wifi = main_wifi
        self.reserve_wlte = reserve_wlte
        self.reserve_wifi = reserve_wifi

    def select(self, configs: List[VPNConfig]) -> Tuple[List[VPNConfig], List[VPNConfig]]:
        wlte = [c for c in configs if c.config_type == ConfigType.WLTE]
        wifi = [c for c in configs if c.config_type == ConfigType.WIFI]
        wlte.sort(key=lambda x: x.composite_score(), reverse=True)
        wifi.sort(key=lambda x: x.composite_score(), reverse=True)
        main, reserves = [], []
        for rank, c in enumerate(wlte[:self.main_wlte], 1):
            c.rank = rank
            main.append(c)
        for rank, c in enumerate(wifi[:self.main_wifi], 1):
            c.rank = rank
            main.append(c)
        reserve_rank = 1
        for c in wlte[self.main_wlte:self.main_wlte + self.reserve_wlte]:
            c.rank = reserve_rank
            c.config_type = ConfigType.RESERVE
            reserves.append(c)
            reserve_rank += 1
        for c in wifi[self.main_wifi:self.main_wifi + self.reserve_wifi]:
            c.rank = reserve_rank
            c.config_type = ConfigType.RESERVE
            reserves.append(c)
            reserve_rank += 1
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
        if include_warp and warp_configs:
            all_cfgs.extend(warp_configs)
        stats = {
            'total': len(all_cfgs),
            'wlte': len([c for c in all_cfgs if c.config_type == ConfigType.WLTE]),
            'wifi': len([c for c in all_cfgs if c.config_type == ConfigType.WIFI]),
            'reserve': len([c for c in all_cfgs if c.config_type == ConfigType.RESERVE])
        }
        with open(output, 'w', encoding='utf-8') as f:
            f.write(f"//profile-title: base64:{cls.TITLE_PLUS if is_plus else cls.TITLE_BALANCED}\n")
            for h in cls.HEADERS_BASE:
                f.write(h + '\n')
            f.write(f"//last update on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            warp_note = ", ночной и стабильный WARP" if include_warp else ""
            f.write(f"// 🪿 {title} - {stats['total']} конфигов, {stats['wlte']} wLTE, {stats['wifi']} WiFi, {stats['reserve']} резервов{warp_note}\n\n")
            sections = [(ConfigType.WLTE,'wLTE'), (ConfigType.WIFI,'WiFi'), (ConfigType.RESERVE,'Резерв')]
            if include_warp:
                sections += [(ConfigType.WARP_STABLE,'WARP Стабильный'), (ConfigType.WARP_NIGHT,'WARP Ночной')]
            for ctype, label in sections:
                group = sorted([c for c in all_cfgs if c.config_type == ctype], key=lambda x: x.rank or 99)
                if not group:
                    continue
                f.write(f"// =-=-=-=-=-= {label} =-=-=-=-=-=\n")
                for cfg in group:
                    f.write(cfg.to_subscription_line() + '\n')
                f.write('\n')
        print(f"✅ {title}: {output} ({stats['total']} конфигов)")

class FunnelPingTester:
    STAGES = [
        {'name': 'Screen', 'concurrent': 25, 'timeout': 1.0, 'keep_ratio': 0.04},
        {'name': 'Mid', 'concurrent': 15, 'timeout': 2.0, 'keep_ratio': 0.25},
        {'name': 'Final', 'concurrent': 10, 'timeout': 3.0, 'keep_ratio': 1.0},
    ]

    def __init__(self, cache: PingCache = None):
        self.cache = cache or PingCache()

    async def _single_test(self, session: aiohttp.ClientSession, host: str, timeout: float) -> Optional[float]:
        try:
            for scheme in ['https', 'http']:
                for attempt in range(3):
                    try:
                        start = asyncio.get_event_loop().time()
                        async with session.get(f"{scheme}://{host}:443/", timeout=timeout, allow_redirects=False):
                            return round((asyncio.get_event_loop().time() - start) * 1000, 1)
                    except aiohttp.client_exceptions.ClientConnectorError as e:
                        if "Temporary failure" in str(e) and attempt < 2:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        break
                    except Exception:
                        break
        except Exception:
            pass
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
                                if self.cache:
                                    self.cache.set(cfg.ip, ping)
                    cfg.speed_score = max(0, 100 - (cfg.ping_ms or 999))
                    cfg.stability_score = random.uniform(0.8, 1.0) if cfg.ping_ms else 0
                return cfg
            return await asyncio.gather(*(test_one(c) for c in configs))

    async def run_funnel(self, configs: List[VPNConfig], final_count: int = 8) -> List[VPNConfig]:
        current = configs.copy()
        for stage in self.STAGES[:-1]:
            if not current:
                break
            tested = await self._test_batch(current, stage['concurrent'], stage['timeout'])
            tested.sort(key=lambda x: x.composite_score(), reverse=True)
            keep_count = max(int(len(tested) * stage['keep_ratio']), final_count * 2)
            current = tested[:keep_count]
            await asyncio.sleep(0.5)
        final_stage = self.STAGES[-1]
        final_tested = await self._test_batch(current, final_stage['concurrent'], final_stage['timeout'])
        final_tested.sort(key=lambda x: x.composite_score(), reverse=True)
        return final_tested[:final_count]

def parse_args():
    p = argparse.ArgumentParser(description="GooseVPN Parser v2.4")
    p.add_argument('-o','--out', type=str, default='configs', help='Output folder')
    p.add_argument('--geo', type=str, help='Path to GeoLite2')
    p.add_argument('--skip-funnel', action='store_true', help='Skip funnel test')
    p.add_argument('--wlte-sources', type=str, default='sources/wlte.txt', help='wLTE sources file')
    p.add_argument('--wifi-sources', type=str, default='sources/wifi.txt', help='WiFi sources file')
    p.add_argument('--only-balanced', action='store_true', help='Only balanced.txt')
    p.add_argument('--only-plus', action='store_true', help='Only plus.txt')
    return p.parse_args()

async def main_async(args):
    print("GooseVPN Parser v2.4")
    geo = GeoLocator(args.geo, auto_cleanup=True)
    cache = PingCache()
    async with aiohttp.ClientSession() as session:
        wlte_fetcher = SourceFetcher(args.wlte_sources, ConfigType.WLTE)
        wifi_fetcher = SourceFetcher(args.wifi_sources, ConfigType.WIFI)
        wlte_cfgs = await wlte_fetcher.fetch_all(session, geo)
        wifi_cfgs = await wifi_fetcher.fetch_all(session, geo)
        warp_cfgs = await WarpSource().fetch(session)
        all_cfgs = wlte_cfgs + wifi_cfgs
        print(f"Loaded: {len(wlte_cfgs)} wLTE + {len(wifi_cfgs)} WiFi = {len(all_cfgs)} total")
        if not args.skip_funnel and all_cfgs:
            tester = FunnelPingTester(cache)
            best_wlte = await tester.run_funnel([c for c in all_cfgs if c.config_type == ConfigType.WLTE], final_count=8)
            best_wifi = await tester.run_funnel([c for c in all_cfgs if c.config_type == ConfigType.WIFI], final_count=8)
            selected = best_wlte + best_wifi
            print(f"After funnel: {len(selected)} best configs")
        else:
            all_cfgs.sort(key=lambda x: x.speed_score, reverse=True)
            selected = all_cfgs[:16]
            print(f"Quick select: {len(selected)} configs")
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        if not args.only_plus:
            filter_b = ConfigFilter(main_wlte=3, main_wifi=3, reserve_wlte=1, reserve_wifi=2)
            main_b, reserves_b = filter_b.select(selected)
            SubscriptionGenerator.generate(main_b, reserves_b, out_dir / "balanced.txt", "GooseVPN", include_warp=False, is_plus=False)
        if not args.only_balanced:
            filter_p = ConfigFilter(main_wlte=4, main_wifi=4, reserve_wlte=2, reserve_wifi=2)
            main_p, reserves_p = filter_p.select(selected)
            SubscriptionGenerator.generate(main_p, reserves_p, out_dir / "plus.txt", "GooseVPN Plus", include_warp=True, warp_configs=warp_cfgs, is_plus=True)
    cache._save()
    geo.close()
    print(f"Done! Files in: ./{args.out}/")

def main():
    args = parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"Error: {e}")
        if '-v' in sys.argv:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
