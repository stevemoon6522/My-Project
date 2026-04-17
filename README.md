# Weverse Shop 범용 크롤러

Weverse Shop의 상품 정보를 자동으로 수집하여 CSV/JSON으로 저장하는 Python 크롤러입니다.

## 주요 기능

- **URL 자동 파싱**: `artist_id`, `category_id`, `subCategoryId`를 URL에서 자동 추출
- **완전한 상품 수집**: 카테고리 + 서브카테고리 순회로 모든 상품 수집
- **상품 상세 정보**: 옵션별(멤버/색상/사이즈), 가격, 재고, 배송 정보 수집
- **3가지 실행 방식**: 대화형 입력, `--url` 인자, `--file` 파일 입력
- **자동 파일명**: `weverse_artist{id}_{카테고리}_{날짜}.csv/json` 형식

## 설치

```bash
pip3 install requests
```

## 실행 방법

### 1. 대화형 모드 (URL 직접 입력)
```bash
python3 weverse_shop_crawler.py
```
실행 후 URL을 한 줄씩 입력하고, 빈 줄에서 Enter를 누르면 시작됩니다.

### 2. 명령행 인자 모드 (`--url`)
```bash
# 단일 URL
python3 weverse_shop_crawler.py --url "https://shop.weverse.io/ko/shop/KRW/artists/155/categories/5438?subCategoryId=7407"

# 여러 URL 동시 처리
python3 weverse_shop_crawler.py --url URL1 URL2 URL3
```

### 3. 파일 입력 모드 (`--file`)
```bash
# urls.txt 파일에 URL 목록 작성
python3 weverse_shop_crawler.py --file urls.txt
```

**urls.txt 형식** (주석 지원):
```
# BTS 앨범 카테고리
https://shop.weverse.io/ko/shop/KRW/artists/2/categories/100

# NCT WISH 투어 굿즈
https://shop.weverse.io/ko/shop/KRW/artists/155/categories/5438?subCategoryId=7407
```

## 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--format` | `both` | 출력 형식: `csv`, `json`, `both` |
| `--output` | `weverse_output` | 저장 폴더 경로 |
| `--detail` | 활성화 | 상품 상세 정보 수집 (옵션, 재고) |
| `--no-detail` | - | 상세 정보 수집 없이 빠른 수집 |
| `--delay` | `0.5` | 요청 간 딜레이 (초) |

## 사용 예시

```bash
# 기본 사용 (CSV + JSON 저장)
python3 weverse_shop_crawler.py --url "https://shop.weverse.io/ko/shop/KRW/artists/155/categories/5438?subCategoryId=7407"

# JSON만 저장, 빠른 수집
python3 weverse_shop_crawler.py --url "..." --format json --no-detail

# 출력 폴더 지정
python3 weverse_shop_crawler.py --url "..." --output ./my_data

# 파일로 여러 URL 처리
python3 weverse_shop_crawler.py --file urls.txt --format csv
```

## 지원 URL 형식

```
https://shop.weverse.io/{locale}/shop/{currency}/artists/{artist_id}/categories/{category_id}
https://shop.weverse.io/{locale}/shop/{currency}/artists/{artist_id}/categories/{category_id}?subCategoryId={sub_id}
```

- `locale`: `ko`, `en`, `ja`, `zh-cn`, `zh-tw`, `es`
- `currency`: `KRW`, `USD`, `JPY`, `CNY`, `MXN`

## 출력 데이터 컬럼

| 컬럼 | 설명 |
|------|------|
| `artist_id` | 아티스트 ID |
| `artist_name` | 아티스트명 |
| `category_id` | 카테고리 ID |
| `sub_category_id` | 서브카테고리 ID |
| `sale_id` | 상품 고유 ID |
| `product_name` | 상품명 |
| `status` | 판매 상태 (SALE/SOLD_OUT/UPCOMING) |
| `original_price` | 정가 |
| `sale_price` | 판매가 |
| `discount_percent` | 할인율 |
| `currency` | 통화 |
| `option_name` | 옵션명 (멤버/색상/사이즈 등) |
| `option_sale_price` | 옵션 판매가 |
| `option_add_price` | 옵션 추가 금액 |
| `is_sold_out` | 품절 여부 |
| `max_order_quantity` | 최대 구매 수량 |
| `available_quantity` | 구매 가능 수량 |
| `goods_type` | 상품 유형 (DELIVERY/DIGITAL 등) |
| `section_type` | 섹션 유형 |
| `icons` | 아이콘 (PRE_ORDER 등) |
| `delivery_date` | 배송 예정일 |
| `pre_order_delivery_start` | 선주문 배송 시작일 |
| `pre_order_delivery_end` | 선주문 배송 종료일 |
| `thumbnail_url` | 상품 이미지 URL |
| `crawled_at` | 수집 시각 |

## 파일명 규칙

```
weverse_artist{ID}_{카테고리명}_{서브카테고리명}_{YYYYMMDD_HHMMSS}.csv
```

예시:
- `weverse_artist155_Tour_Merch_IN_TO_THE_WISH_20260417_120000.csv`
- `weverse_artist2_Album_20260417_120000.json`

## 테스트 URL

```
https://shop.weverse.io/ko/shop/KRW/artists/155/categories/5438?subCategoryId=7407
```
(NCT WISH - Tour Merch - IN TO THE WISH : Our WISH ENCORE IN SEOUL)

## 주의사항

- 과도한 요청은 서버 부하를 유발할 수 있습니다. 기본 딜레이(0.5초)를 유지하세요.
- Weverse Shop의 로그인 없이 공개된 상품 정보만 수집합니다.
- 사이트 구조 변경 시 `Build ID` 자동 갱신 로직이 대응합니다.
- 재고 수량은 주문 제한 수량(`available_quantity`)으로 표시됩니다.
