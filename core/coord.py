"""坐标系服务:BD-09 / GCJ-02 / WGS-84 互转 + 射线采样点生成。

对应实验设计 E1(坐标系一致性)与 E4(扇形采样)。
业务代码禁止自行转换坐标,一律经由本模块 —— 参见 09-API工程 §9.4。
"""
import math

X_PI = math.pi * 3000.0 / 180.0
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lng: float, lat: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(lng: float, lat: float) -> float:
    ret = (-100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat
           + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng)))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = (300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat
           + 0.1 * math.sqrt(abs(lng)))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple:
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng: float, lat: float) -> tuple:
    """逆变换:不动点迭代(一阶近似误差 ~2.6m,3 轮迭代收敛到 <1mm)。"""
    wlng, wlat = lng, lat
    for _ in range(3):
        glng, glat = wgs84_to_gcj02(wlng, wlat)
        wlng, wlat = wlng - (glng - lng), wlat - (glat - lat)
    return wlng, wlat


def gcj02_to_bd09(lng: float, lat: float) -> tuple:
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(bd_lng: float, bd_lat: float) -> tuple:
    x = bd_lng - 0.0065
    y = bd_lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def bd09_to_wgs84(lng: float, lat: float) -> tuple:
    g = bd09_to_gcj02(lng, lat)
    return gcj02_to_wgs84(*g)


def wgs84_to_bd09(lng: float, lat: float) -> tuple:
    g = wgs84_to_gcj02(lng, lat)
    return gcj02_to_bd09(*g)


def haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点球面距离(米)。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dest_at(lng: float, lat: float, bearing_deg: float, dist_m: float) -> tuple:
    """从 (lng,lat) 沿方位角(正北为 0°,顺时针)前进 dist_m 米的近似坐标。

    1–2km 尺度下等距圆柱近似的误差可忽略(< 1m)。
    """
    lat_r = math.radians(lat)
    dlng = dist_m * math.sin(math.radians(bearing_deg)) / (111320.0 * math.cos(lat_r))
    dlat = dist_m * math.cos(math.radians(bearing_deg)) / 111320.0
    return lat + dlat, lng + dlng   # 统一返回 (lat, lng)
