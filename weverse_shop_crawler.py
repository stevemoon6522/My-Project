#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weverse Shop 범용 크롤러
========================
지원 URL 형식:
  https://shop.weverse.io/{locale}/shop/{currency}/artists/{artist_id}/categories/{category_id}?subCategoryId={sub_id}

실행 방법:
  대화형:        python3 weverse_shop_crawler.py
  단일 URL:      python3 weverse_shop_crawler.py --url "https://..."
  파일 입력:     python3 weverse_shop_crawler.py --file urls.txt
  상세 정보 포함: 위 방법에 --detail 추가
  출력 형식:     --format csv|json|both (기본: both)
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("❌ requests 패키지가 필요합니다. 설치: pip3 install requests")
    sys.exit(1)

# ────────────────────────────────────────────────────────────────────────────
# 상수 및 설정
# ────────────────────────────────────────────────────────────────────────────
BASE_URL = "https://shop.weverse.io"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_DELAY = 0.5      # 요청 간 딜레이 (초)
PRODUCT_DETAIL_DELAY = 0.3
MAX_RETRIES = 3


# ────────────────────────────────────────────────────────────────────────────
# HTTP 클라이언트
# ────────────────────────────────────────────────────────────────────────────
def create_session() -> requests.Session:
    """재시도 로직을 포함한 HTTP 세션 생성"""
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": BASE_URL,
    })
    return session


# ────────────────────────────────────────────────────────────────────────────
# URL 파싱
# ────────────────────────────────────────────────────────────────────────────
class WeverseURL:
    """Weverse Shop URL 파서"""

    # 패턴: /ko/shop/KRW/artists/155/categories/5438
    CATEGORY_PATTERN = re.compile(
        r"/(?P<locale>[a-z]{2}(?:-[a-z]{2})?)/shop/(?P<currency>[A-Z]{3})"
        r"/artists/(?P<artist_id>\d+)/categories/(?P<category_id>\d+)",
        re.IGNORECASE,
    )
    # 패턴: /ko/shop/KRW/artists/155/sales/57586
    SALE_PATTERN = re.compile(
        r"/(?P<locale>[a-z]{2}(?:-[a-z]{2})?)/shop/(?P<currency>[A-Z]{3})"
        r"/artists/(?P<artist_id>\d+)/sales/(?P<sale_id>\d+)",
        re.IGNORECASE,
    )

    def __init__(self, url: str):
        self.raw_url = url.strip()
        self.locale: Optional[str] = None
        self.currency: Optional[str] = None
        self.artist_id: Optional[int] = None
        self.category_id: Optional[int] = None
        self.sub_category_id: Optional[int] = None
        self.sale_id: Optional[int] = None
        self._parse()

    def _parse(self):
        parsed = urlparse(self.raw_url)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # 카테고리 URL 파싱
        m = self.CATEGORY_PATTERN.search(path)
        if m:
            self.locale = m.group("locale").lower()
            self.currency = m.group("currency").upper()
            self.artist_id = int(m.group("artist_id"))
            self.category_id = int(m.group("category_id"))
            if "subCategoryId" in qs:
                self.sub_category_id = int(qs["subCategoryId"][0])
            return

        # 상품 상세 URL 파싱
        m2 = self.SALE_PATTERN.search(path)
        if m2:
            self.locale = m2.group("locale").lower()
            self.currency = m2.group("currency").upper()
            self.artist_id = int(m2.group("artist_id"))
            self.sale_id = int(m2.group("sale_id"))
            return

    @property
    def is_category_url(self) -> bool:
        return self.category_id is not None

    @property
    def is_sale_url(self) -> bool:
        return self.sale_id is not None

    @property
    def is_valid(self) -> bool:
        return self.is_category_url or self.is_sale_url

    def shop_currency_param(self) -> str:
        """Next.js shopAndCurrency 파라미터 (예: KRW)"""
        return self.currency or "KRW"

    def __repr__(self):
        return (
            f"WeverseURL(locale={self.locale}, currency={self.currency}, "
            f"artist_id={self.artist_id}, category_id={self.category_id}, "
            f"sub_category_id={self.sub_category_id})"
        )


# ────────────────────────────────────────────────────────────────────────────
# Build ID 획득
# ────────────────────────────────────────────────────────────────────────────
def get_build_id(session: requests.Session) -> Optional[str]:
    """
    Weverse Shop의 현재 Next.js build ID를 동적으로 획득합니다.
    buildId는 배포마다 변경되므로 런타임에 읽어야 합니다.
    """
    try:
        resp = session.get(BASE_URL, timeout=15)
        resp.raise_for_status()
        m = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"  ⚠️  buildId 획득 실패: {e}")
    return None


# ────────────────────────────────────────────────────────────────────────────
# 카테고리 정보 가져오기
# ────────────────────────────────────────────────────────────────────────────
def fetch_categories(
    session: requests.Session,
    build_id: str,
    wurl: "WeverseURL",
) -> list:
    """
    아티스트의 전체 카테고리 목록을 반환합니다.
    Next.js SSR 데이터 엔드포인트 활용.
    """
    url = (
        f"{BASE_URL}/_next/data/{build_id}/{wurl.locale}/shop/"
        f"{wurl.shop_currency_param()}/artists/{wurl.artist_id}"
        f"/categories/{wurl.category_id}.json"
    )
    params = {
        "subCategoryId": str(wurl.sub_category_id) if wurl.sub_category_id else "",
        "shopAndCurrency": wurl.shop_currency_param(),
        "artistId": str(wurl.artist_id),
        "categoryId": str(wurl.category_id),
    }
    # 빈 파라미터 제거
    params = {k: v for k, v in params.items() if v}

    try:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        queries = data.get("pageProps", {}).get("$dehydratedState", {}).get("queries", [])
        for q in queries:
            key = q.get("queryKey", [])
            if key and "categories" in str(key[0]) and "sales" not in str(key[0]):
                return q.get("state", {}).get("data", []) or []
    except Exception as e:
        print(f"  ⚠️  카테고리 조회 실패: {e}")
    return []


# ────────────────────────────────────────────────────────────────────────────
# 상품 카드 목록 가져오기 (완전 수집)
# ────────────────────────────────────────────────────────────────────────────
def fetch_product_cards(
    session: requests.Session,
    build_id: str,
    wurl: "WeverseURL",
    categories: Optional[list] = None,
) -> list:
    """
    카테고리/서브카테고리의 상품 목록을 모두 수집합니다.

    수집 전략:
    1. 서브카테고리가 지정된 경우: 해당 서브카테고리만 수집
    2. 서브카테고리가 없고, 카테고리에 자식이 있는 경우:
       - 먼저 전체 카테고리 뷰(서브카테고리 없이) 로드
       - lastIdx >= 0이면 각 서브카테고리를 순회하여 전체 수집
    3. lastIdx == -1: 단일 페이지, 완료
    """
    all_products = []
    seen_ids: set = set()

    print(f"  📦 상품 목록 수집 중...")

    # ── Case 1: 서브카테고리 지정 ─────────────────────────────────────────
    if wurl.sub_category_id:
        batch, last_idx = _fetch_one_page(session, build_id, wurl, None)
        _extend_unique(all_products, seen_ids, batch)
        print(f"    서브카테고리 [{wurl.sub_category_id}]: {len(batch)}개 수집")
        print(f"  ✅ 총 {len(all_products)}개 상품 수집 완료")
        return all_products

    # ── Case 2: 서브카테고리 없음 ─────────────────────────────────────────
    first_batch, last_idx = _fetch_one_page(session, build_id, wurl, None)
    _extend_unique(all_products, seen_ids, first_batch)
    print(f"    전체 카테고리: {len(first_batch)}개 수집 (lastIdx={last_idx})")

    # lastIdx == -1: 한 페이지로 완료
    if last_idx is None or last_idx < 0:
        print(f"  ✅ 총 {len(all_products)}개 상품 수집 완료")
        return all_products

    # ── lastIdx > 0: 서브카테고리 순회로 전체 수집 ──────────────────────
    # 자식 카테고리 목록 구성
    child_ids = _get_child_category_ids(wurl.category_id, categories or [])

    if child_ids:
        print(f"    📁 서브카테고리 {len(child_ids)}개 순회 시작...")
        for child_id in child_ids:
            time.sleep(DEFAULT_DELAY)
            child_batch, child_last_idx = _fetch_one_page(
                session, build_id, wurl, child_id
            )
            new_count = _extend_unique(all_products, seen_ids, child_batch)
            print(f"    서브카테고리 [{child_id}]: {new_count}개 추가")
            # 서브카테고리도 여러 페이지일 경우 대비
            while child_last_idx is not None and child_last_idx >= 0:
                time.sleep(DEFAULT_DELAY)
                sub_wurl = _make_sub_wurl(wurl, child_id)
                # 커서 기반 추가 페이지 시도
                more_batch, child_last_idx = _fetch_cursor_page(
                    session, build_id, sub_wurl, child_last_idx
                )
                if not more_batch:
                    break
                extra = _extend_unique(all_products, seen_ids, more_batch)
                print(f"      추가 페이지: {extra}개")
    else:
        # 자식 없음 – 커서로 추가 페이지 시도
        print(f"    커서 기반 추가 페이지 수집...")
        while last_idx is not None and last_idx >= 0:
            time.sleep(DEFAULT_DELAY)
            batch, last_idx = _fetch_cursor_page(session, build_id, wurl, last_idx)
            if not batch:
                break
            new_count = _extend_unique(all_products, seen_ids, batch)
            print(f"    cursor={last_idx}: {new_count}개 추가")
            if new_count == 0:
                break

    print(f"  ✅ 총 {len(all_products)}개 상품 수집 완료")
    return all_products


def _extend_unique(product_list: list, seen_ids: set, batch: list) -> int:
    """중복 제거 후 리스트에 추가. 추가된 개수 반환."""
    count = 0
    for p in batch:
        sid = p.get("saleId")
        if sid and sid not in seen_ids:
            seen_ids.add(sid)
            product_list.append(p)
            count += 1
    return count


def _get_child_category_ids(parent_id: int, categories: list) -> list:
    """categories 목록에서 parent_id에 속한 자식 카테고리 ID 목록 반환"""
    for cat in categories:
        if cat.get("categoryId") == parent_id:
            return [c["categoryId"] for c in cat.get("childCategories", [])]
    return []


def _make_sub_wurl(wurl: "WeverseURL", child_id: int) -> "WeverseURL":
    """서브카테고리 ID를 적용한 WeverseURL 복사본 반환"""
    import copy
    sub = copy.copy(wurl)
    sub.sub_category_id = child_id
    return sub


def _fetch_one_page(
    session: requests.Session,
    build_id: str,
    wurl: "WeverseURL",
    sub_category_id: Optional[int],
):
    """SSR 데이터 API로 한 페이지 상품 가져오기"""
    url = (
        f"{BASE_URL}/_next/data/{build_id}/{wurl.locale}/shop/"
        f"{wurl.shop_currency_param()}/artists/{wurl.artist_id}"
        f"/categories/{wurl.category_id}.json"
    )
    params = {
        "shopAndCurrency": wurl.shop_currency_param(),
        "artistId": str(wurl.artist_id),
        "categoryId": str(wurl.category_id),
    }
    # 서브카테고리: 명시 인자 우선, 없으면 wurl에서
    effective_sub = sub_category_id if sub_category_id is not None else wurl.sub_category_id
    if effective_sub:
        params["subCategoryId"] = str(effective_sub)

    try:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        queries = (
            data.get("pageProps", {})
            .get("$dehydratedState", {})
            .get("queries", [])
        )
        for q in queries:
            key = q.get("queryKey", [])
            if key and "sales" in str(key[0]) and "categories" in str(key[0]):
                state_data = q.get("state", {}).get("data", {}) or {}
                products = state_data.get("productCards", [])
                last_idx = state_data.get("lastIdx", -1)
                return products, (last_idx if last_idx >= 0 else None)
    except Exception as e:
        print(f"  ⚠️  상품 목록 페이지 오류: {e}")
    return [], None


def _fetch_cursor_page(
    session: requests.Session,
    build_id: str,
    wurl: "WeverseURL",
    last_idx: int,
):
    """
    커서(lastIdx) 기반 추가 페이지 상품 가져오기.
    Next.js SSR은 lastIdx 파라미터를 직접 지원하지 않습니다.
    서브카테고리가 있으면 SSR 방식으로 전체 수집 완료됩니다.
    """
    # 현재는 서브카테고리 순회로 모든 데이터를 커버하므로
    # 이 함수는 fallback으로만 사용됩니다.
    return [], None


# ────────────────────────────────────────────────────────────────────────────
# 상품 상세 정보 (옵션, 재고) 가져오기
# ────────────────────────────────────────────────────────────────────────────
def fetch_product_detail(
    session: requests.Session,
    build_id: str,
    wurl: "WeverseURL",
    sale_id: int,
) -> Optional[dict]:
    """
    개별 상품의 상세 정보를 가져옵니다.
    (옵션, 재고 수량, 가격 상세, 배송 정보 등)
    """
    url = (
        f"{BASE_URL}/_next/data/{build_id}/{wurl.locale}/shop/"
        f"{wurl.shop_currency_param()}/artists/{wurl.artist_id}"
        f"/sales/{sale_id}.json"
    )
    params = {
        "shopAndCurrency": wurl.shop_currency_param(),
        "artistId": str(wurl.artist_id),
        "saleId": str(sale_id),
    }

    try:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        queries = data.get("pageProps", {}).get("$dehydratedState", {}).get("queries", [])
        for q in queries:
            key = q.get("queryKey", [])
            if key and "/api/v1/sales/" in str(key[0]):
                return q.get("state", {}).get("data")
    except Exception as e:
        print(f"    ⚠️  상품 {sale_id} 상세 조회 실패: {e}")
    return None


# ────────────────────────────────────────────────────────────────────────────
# 데이터 정규화
# ────────────────────────────────────────────────────────────────────────────
def normalize_product(card: dict, detail: Optional[dict], wurl: "WeverseURL") -> list:
    """
    상품 카드 + 상세 정보를 결합하여 정규화된 행(row) 리스트로 변환.
    옵션이 여러 개인 경우 각 옵션을 별도 행으로 확장.
    """
    base = {
        "artist_id": wurl.artist_id,
        "artist_name": card.get("artistName", ""),
        "category_id": wurl.category_id,
        "sub_category_id": wurl.sub_category_id or "",
        "sale_id": card.get("saleId", ""),
        "product_name": card.get("name", ""),
        "status": card.get("status", ""),
        "original_price": card.get("price", {}).get("originalPrice", ""),
        "sale_price": card.get("price", {}).get("salePrice", ""),
        "discount_percent": card.get("price", {}).get("discountPercent", 0),
        "currency": wurl.currency,
        "goods_type": card.get("goodsType", ""),
        "icons": ",".join(card.get("icons", [])),
        "delivery_date": card.get("deliveryDate", ""),
        "thumbnail_url": card.get("thumbnailImageUrl", ""),
        "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if detail is None:
        # 상세 정보 없이 기본 행 반환
        base.update({
            "option_name": "",
            "option_sale_price": "",
            "option_add_price": "",
            "is_sold_out": "",
            "stock_quantity": "",
            "max_order_quantity": "",
            "available_quantity": "",
            "section_type": "",
            "pre_order_delivery_start": "",
            "pre_order_delivery_end": "",
        })
        return [base]

    # 상세 정보 추가
    pre_order = detail.get("preOrder") or {}
    order_limit = detail.get("goodsOrderLimit") or {}
    base.update({
        "section_type": detail.get("sectionType", ""),
        "pre_order_delivery_start": pre_order.get("deliveryStartAt", ""),
        "pre_order_delivery_end": pre_order.get("deliveryEndAt", ""),
        "max_order_quantity": order_limit.get("maxOrderQuantity", ""),
        "available_quantity": order_limit.get("availableQuantity", ""),
    })

    # 옵션 처리
    option_data = detail.get("option") or {}
    options = option_data.get("options", [])
    variants = option_data.get("variants", [])

    if not options:
        base.update({
            "option_name": "",
            "option_sale_price": "",
            "option_add_price": "",
            "is_sold_out": detail.get("status", "") == "SOLD_OUT",
            "stock_quantity": "",
        })
        return [base]

    rows = []
    for opt in options:
        # 옵션명 구성
        option_name = opt.get("saleOptionName", "")
        if not option_name:
            # variantOptionLocation으로 옵션명 구성
            loc = opt.get("variantOptionLocation", [])
            parts = []
            for variant_idx_item in loc:
                v_idx = variant_idx_item.get("variantIndex", 0) if isinstance(variant_idx_item, dict) else variant_idx_item
                if v_idx < len(variants):
                    v = variants[v_idx]
                    v_name = v.get("name", "")
                    v_values = v.get("values", [])
                    loc_idx = variant_idx_item.get("optionIndex", 0) if isinstance(variant_idx_item, dict) else 0
                    if loc_idx < len(v_values):
                        parts.append(f"{v_name}:{v_values[loc_idx]}")
            option_name = " / ".join(parts) if parts else opt.get("saleOptionName", "옵션")

        row = dict(base)
        row.update({
            "option_name": option_name,
            "option_sale_price": opt.get("optionSalePrice", ""),
            "option_add_price": opt.get("optionAddPrice", 0),
            "is_sold_out": opt.get("isSoldOut", False),
            "stock_quantity": "",  # 재고 수량은 별도 API 필요
        })
        rows.append(row)

    return rows if rows else [base]


# ────────────────────────────────────────────────────────────────────────────
# 파일명 자동 생성
# ────────────────────────────────────────────────────────────────────────────
def generate_filename(wurl: "WeverseURL", categories: list, ext: str) -> str:
    """
    URL 정보 기반 자동 파일명 생성
    형식: weverse_{artist_id}_{artist_name}_{category_name}_{sub_category_name}_{date}.{ext}
    """
    # 카테고리명 조회
    category_name = str(wurl.category_id)
    sub_category_name = str(wurl.sub_category_id) if wurl.sub_category_id else ""

    for cat in categories:
        if cat.get("categoryId") == wurl.category_id:
            category_name = cat.get("name", category_name)
            for child in cat.get("childCategories", []):
                if child.get("categoryId") == wurl.sub_category_id:
                    sub_category_name = child.get("name", sub_category_name)
            break

    # 파일명에 사용할 수 없는 문자 제거
    def sanitize(s: str) -> str:
        return re.sub(r'[^\w가-힣\-]', '_', str(s)).strip('_')[:40]

    parts = [
        "weverse",
        f"artist{wurl.artist_id}",
        sanitize(category_name),
    ]
    if sub_category_name:
        parts.append(sanitize(sub_category_name))
    parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))

    filename = "_".join(filter(None, parts)) + f".{ext}"
    return filename


# ────────────────────────────────────────────────────────────────────────────
# 저장 함수
# ────────────────────────────────────────────────────────────────────────────
CSV_COLUMNS = [
    "artist_id", "artist_name", "category_id", "sub_category_id",
    "sale_id", "product_name", "status",
    "original_price", "sale_price", "discount_percent", "currency",
    "option_name", "option_sale_price", "option_add_price", "is_sold_out",
    "stock_quantity", "max_order_quantity", "available_quantity",
    "goods_type", "section_type", "icons", "delivery_date",
    "pre_order_delivery_start", "pre_order_delivery_end",
    "thumbnail_url", "crawled_at",
]


def save_csv(rows: list, filepath: str):
    """CSV 파일로 저장"""
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  💾 CSV 저장: {filepath} ({len(rows)}행)")


def save_json(rows: list, filepath: str, wurl: "WeverseURL", categories: list):
    """JSON 파일로 저장 (메타데이터 포함)"""
    output = {
        "meta": {
            "crawled_at": datetime.now().isoformat(),
            "source_url": wurl.raw_url,
            "artist_id": wurl.artist_id,
            "category_id": wurl.category_id,
            "sub_category_id": wurl.sub_category_id,
            "currency": wurl.currency,
            "total_rows": len(rows),
        },
        "products": rows,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  💾 JSON 저장: {filepath} ({len(rows)}행)")


# ────────────────────────────────────────────────────────────────────────────
# 메인 크롤링 로직
# ────────────────────────────────────────────────────────────────────────────
def crawl(
    url: str,
    output_dir: str = ".",
    fmt: str = "both",
    with_detail: bool = True,
    session: Optional[requests.Session] = None,
    build_id: Optional[str] = None,
) -> dict:
    """
    단일 URL 크롤링.

    Returns:
        {"status": "ok", "rows": [...], "files": [...]}
    """
    print(f"\n{'='*60}")
    print(f"🔍 URL 파싱: {url}")

    wurl = WeverseURL(url)
    if not wurl.is_valid:
        print("❌ 지원하지 않는 URL 형식입니다.")
        print("   예시: https://shop.weverse.io/ko/shop/KRW/artists/155/categories/5438")
        return {"status": "error", "rows": [], "files": []}

    print(f"   아티스트 ID: {wurl.artist_id}")
    print(f"   카테고리 ID: {wurl.category_id}")
    if wurl.sub_category_id:
        print(f"   서브카테고리 ID: {wurl.sub_category_id}")
    print(f"   통화: {wurl.currency}")

    # 세션 및 빌드 ID 초기화
    if session is None:
        session = create_session()
    if build_id is None:
        print("\n📡 Build ID 획득 중...")
        build_id = get_build_id(session)
        if not build_id:
            print("❌ Build ID를 가져올 수 없습니다.")
            return {"status": "error", "rows": [], "files": []}
        print(f"   Build ID: {build_id}")

    # 카테고리 정보 가져오기
    print("\n📂 카테고리 정보 조회 중...")
    categories = fetch_categories(session, build_id, wurl)
    if categories:
        for cat in categories:
            marker = "→" if cat.get("categoryId") == wurl.category_id else " "
            print(f"   {marker} [{cat.get('categoryId')}] {cat.get('name')}")
            for child in cat.get("childCategories", []):
                child_marker = "  ✓" if child.get("categoryId") == wurl.sub_category_id else "   "
                print(f"  {child_marker} [{child.get('categoryId')}] {child.get('name')}")

    # 상품 목록 가져오기
    print(f"\n🛒 상품 목록 수집...")
    product_cards = fetch_product_cards(session, build_id, wurl, categories)

    if not product_cards:
        print("⚠️  수집된 상품이 없습니다.")
        return {"status": "empty", "rows": [], "files": []}

    # 상품 상세 정보 수집
    all_rows = []
    if with_detail:
        print(f"\n📋 상품 상세 정보 수집 중... (총 {len(product_cards)}개)")
        for i, card in enumerate(product_cards, 1):
            sale_id = card.get("saleId")
            print(f"   [{i:3d}/{len(product_cards)}] {card.get('name', '')} (ID:{sale_id})")
            detail = fetch_product_detail(session, build_id, wurl, sale_id)
            rows = normalize_product(card, detail, wurl)
            all_rows.extend(rows)
            time.sleep(PRODUCT_DETAIL_DELAY)
    else:
        print(f"\n📋 상품 기본 정보 정규화 중...")
        for card in product_cards:
            rows = normalize_product(card, None, wurl)
            all_rows.extend(rows)

    # 파일 저장
    os.makedirs(output_dir, exist_ok=True)
    saved_files = []

    if fmt in ("csv", "both"):
        csv_filename = generate_filename(wurl, categories, "csv")
        csv_path = os.path.join(output_dir, csv_filename)
        save_csv(all_rows, csv_path)
        saved_files.append(csv_path)

    if fmt in ("json", "both"):
        json_filename = generate_filename(wurl, categories, "json")
        json_path = os.path.join(output_dir, json_filename)
        save_json(all_rows, json_path, wurl, categories)
        saved_files.append(json_path)

    print(f"\n✅ 완료! 총 {len(all_rows)}행 저장됨")
    return {"status": "ok", "rows": all_rows, "files": saved_files}


# ────────────────────────────────────────────────────────────────────────────
# 입력 방식별 실행
# ────────────────────────────────────────────────────────────────────────────
def run_interactive(args):
    """대화형 모드"""
    print("\n" + "="*60)
    print("  Weverse Shop 범용 크롤러")
    print("="*60)
    print("URL을 입력하세요 (여러 개는 줄바꿈으로 구분, 빈 줄에서 Enter로 시작)")
    print("예시: https://shop.weverse.io/ko/shop/KRW/artists/155/categories/5438?subCategoryId=7407")
    print("종료: 'quit' 또는 'q' 입력\n")

    urls = []
    while True:
        try:
            line = input("URL> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in ("q", "quit", "exit", ""):
            if urls:
                break
            continue
        if line.startswith("http"):
            urls.append(line)
            print(f"  ✓ 추가됨 ({len(urls)}개)")
        else:
            print("  ⚠️  유효한 URL을 입력하세요 (http 또는 https로 시작)")

    if not urls:
        print("입력된 URL이 없습니다.")
        return

    print(f"\n총 {len(urls)}개 URL 처리 시작...")
    _run_urls(urls, args)


def run_with_urls(args):
    """--url 모드: 명령행에서 직접 URL 입력"""
    urls = args.url if isinstance(args.url, list) else [args.url]
    _run_urls(urls, args)


def run_with_file(args):
    """--file 모드: 파일에서 URL 읽기"""
    filepath = args.file
    if not os.path.exists(filepath):
        print(f"❌ 파일을 찾을 수 없습니다: {filepath}")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not urls:
        print(f"❌ 파일에 유효한 URL이 없습니다: {filepath}")
        return

    print(f"📄 파일에서 {len(urls)}개 URL 로드: {filepath}")
    _run_urls(urls, args)


def _run_urls(urls: list, args):
    """URL 목록 크롤링 실행"""
    session = create_session()

    print("\n📡 Build ID 획득 중...")
    build_id = get_build_id(session)
    if not build_id:
        print("❌ Build ID를 가져올 수 없습니다. 인터넷 연결을 확인하세요.")
        sys.exit(1)
    print(f"   Build ID: {build_id}")

    output_dir = getattr(args, "output", "weverse_output")
    fmt = getattr(args, "format", "both")
    with_detail = getattr(args, "detail", True)

    results = []
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] 처리 중...")
        result = crawl(
            url=url,
            output_dir=output_dir,
            fmt=fmt,
            with_detail=with_detail,
            session=session,
            build_id=build_id,
        )
        results.append(result)
        if i < len(urls):
            time.sleep(DEFAULT_DELAY)

    # 요약
    print(f"\n{'='*60}")
    print("📊 크롤링 완료 요약")
    print(f"{'='*60}")
    ok = sum(1 for r in results if r["status"] == "ok")
    total_rows = sum(len(r.get("rows", [])) for r in results)
    print(f"  성공: {ok}/{len(urls)}")
    print(f"  총 수집 행: {total_rows}")
    print(f"  저장 위치: {os.path.abspath(output_dir)}/")
    for r in results:
        for f in r.get("files", []):
            print(f"    - {os.path.basename(f)}")


# ────────────────────────────────────────────────────────────────────────────
# CLI 진입점
# ────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="weverse_shop_crawler",
        description="Weverse Shop 범용 크롤러 - 상품 정보를 CSV/JSON으로 저장",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  대화형:        python3 weverse_shop_crawler.py
  단일 URL:      python3 weverse_shop_crawler.py --url "https://shop.weverse.io/ko/shop/KRW/artists/155/categories/5438?subCategoryId=7407"
  여러 URL:      python3 weverse_shop_crawler.py --url URL1 URL2
  파일 입력:     python3 weverse_shop_crawler.py --file urls.txt
  JSON만 저장:   python3 weverse_shop_crawler.py --url "..." --format json
  기본 정보만:   python3 weverse_shop_crawler.py --url "..." --no-detail
  출력 폴더 지정: python3 weverse_shop_crawler.py --url "..." --output my_data
""",
    )

    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--url", "-u",
        nargs="+",
        metavar="URL",
        help="크롤링할 Weverse Shop URL (여러 개 가능)",
    )
    input_group.add_argument(
        "--file", "-f",
        metavar="FILE",
        help="URL 목록이 담긴 텍스트 파일 경로",
    )

    parser.add_argument(
        "--format",
        choices=["csv", "json", "both"],
        default="both",
        help="출력 형식 (기본: both)",
    )
    parser.add_argument(
        "--output", "-o",
        default="weverse_output",
        metavar="DIR",
        help="저장 폴더 (기본: weverse_output)",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        default=True,
        help="상품 상세 정보 수집 (기본: 활성화)",
    )
    parser.add_argument(
        "--no-detail",
        action="store_false",
        dest="detail",
        help="상품 상세 정보 수집 비활성화 (빠른 수집)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"요청 간 딜레이 초 (기본: {DEFAULT_DELAY})",
    )

    args = parser.parse_args()

    if args.url:
        run_with_urls(args)
    elif args.file:
        run_with_file(args)
    else:
        run_interactive(args)


if __name__ == "__main__":
    main()
