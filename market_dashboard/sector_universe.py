"""주식 섹터 대시보드의 대상: 나라별 섹터 ETF(지도에 찍는 점)와 섹터별 대표 종목(편입 후보).

섹터 강도는 섹터 ETF 가격으로, 종목 순위는 각 종목 가격으로 계산한다(모두 현지 통화).
종목 목록은 지금 시점의 대표 종목을 고정해 둔 것이라 가끔 손봐야 한다. 그사이 망한 종목이 빠져 있어서
(생존 편향) 종목 순위는 백테스트하지 않고 '후보 좁히기' 용도로만 쓴다.
한국 종목코드·ETF 코드는 실행 로그의 '받지 못한 티커' 목록으로 확인한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sector:
    key: str
    name: str
    etf: str                      # Yahoo 티커
    etf_name: str
    stocks: dict[str, str] = field(default_factory=dict)   # Yahoo 티커 → 종목명


@dataclass(frozen=True)
class Country:
    key: str
    name: str
    currency: str
    benchmark: str                # 지수 대용 ETF
    benchmark_name: str
    cash: str                     # 현금 기준선(미국: ^IRX 금리, 한국: 단기채권 ETF 가격)
    cash_is_rate: bool
    min_value: float              # 종목 유동성 기준(최근 20일 평균 거래대금, 현지 통화)
    sectors: list[Sector]


def _kr(d: dict[str, str], suffix: str = ".KS") -> dict[str, str]:
    return {(k if "." in k else k + suffix): v for k, v in d.items()}


US = Country(
    "US", "미국", "USD", "SPY", "S&P500(SPY)", "^IRX", True, 50e6, [
        Sector("XLK", "기술", "XLK", "Technology Select Sector SPDR", {
            "AAPL": "애플", "MSFT": "마이크로소프트", "NVDA": "엔비디아", "AVGO": "브로드컴", "ORCL": "오라클",
            "CRM": "세일즈포스", "AMD": "AMD", "ADBE": "어도비", "CSCO": "시스코", "ACN": "액센추어", "IBM": "IBM",
            "NOW": "서비스나우"}),
        Sector("SMH", "반도체", "SMH", "VanEck Semiconductor", {
            "NVDA": "엔비디아", "TSM": "TSMC", "AVGO": "브로드컴", "AMD": "AMD", "ASML": "ASML", "QCOM": "퀄컴",
            "TXN": "텍사스인스트루먼트", "MU": "마이크론", "AMAT": "어플라이드머티리얼즈", "LRCX": "램리서치",
            "KLAC": "KLA", "INTC": "인텔"}),
        Sector("XLF", "금융", "XLF", "Financial Select Sector SPDR", {
            "BRK-B": "버크셔해서웨이", "JPM": "JP모건", "V": "비자", "MA": "마스터카드", "BAC": "뱅크오브아메리카",
            "WFC": "웰스파고", "GS": "골드만삭스", "MS": "모건스탠리", "SPGI": "S&P글로벌", "AXP": "아메리칸익스프레스",
            "BLK": "블랙록", "C": "씨티그룹"}),
        Sector("XLV", "헬스케어", "XLV", "Health Care Select Sector SPDR", {
            "LLY": "일라이릴리", "UNH": "유나이티드헬스", "JNJ": "존슨앤드존슨", "ABBV": "애브비", "MRK": "머크",
            "TMO": "써모피셔", "ABT": "애보트", "ISRG": "인튜이티브서지컬", "AMGN": "암젠", "PFE": "화이자",
            "DHR": "다나허", "BSX": "보스턴사이언티픽"}),
        Sector("XLE", "에너지", "XLE", "Energy Select Sector SPDR", {
            "XOM": "엑슨모빌", "CVX": "셰브론", "COP": "코노코필립스", "EOG": "EOG리소스", "SLB": "슐럼버거",
            "MPC": "마라톤페트롤리엄", "PSX": "필립스66", "WMB": "윌리엄스", "OKE": "원옥", "VLO": "발레로",
            "KMI": "킨더모건", "OXY": "옥시덴탈"}),
        Sector("XLI", "산업재", "XLI", "Industrial Select Sector SPDR", {
            "GE": "GE에어로스페이스", "CAT": "캐터필러", "RTX": "RTX", "UBER": "우버", "HON": "허니웰",
            "UNP": "유니온퍼시픽", "ETN": "이튼", "LMT": "록히드마틴", "DE": "디어", "BA": "보잉", "ADP": "ADP",
            "GEV": "GE버노바"}),
        Sector("XLY", "경기소비재", "XLY", "Consumer Discretionary Select Sector SPDR", {
            "AMZN": "아마존", "TSLA": "테슬라", "HD": "홈디포", "MCD": "맥도날드", "BKNG": "부킹홀딩스", "LOW": "로우스",
            "TJX": "TJX", "NKE": "나이키", "SBUX": "스타벅스", "CMG": "치폴레", "ORLY": "오라일리", "MAR": "메리어트"}),
        Sector("XLP", "필수소비재", "XLP", "Consumer Staples Select Sector SPDR", {
            "PG": "P&G", "COST": "코스트코", "WMT": "월마트", "KO": "코카콜라", "PEP": "펩시코", "PM": "필립모리스",
            "MO": "알트리아", "MDLZ": "몬델리즈", "CL": "콜게이트", "KMB": "킴벌리클라크", "TGT": "타깃", "KR": "크로거"}),
        Sector("XLU", "유틸리티", "XLU", "Utilities Select Sector SPDR", {
            "NEE": "넥스트에라", "SO": "서던", "DUK": "듀크에너지", "CEG": "컨스텔레이션", "AEP": "AEP", "SRE": "셈프라",
            "D": "도미니언", "VST": "비스트라", "EXC": "엑셀론", "XEL": "엑셀에너지", "PCG": "PG&E", "PEG": "PSEG"}),
        Sector("XLB", "소재", "XLB", "Materials Select Sector SPDR", {
            "LIN": "린데", "SHW": "셔윈윌리엄스", "APD": "에어프로덕츠", "ECL": "에코랩", "FCX": "프리포트맥모란",
            "NEM": "뉴몬트", "CTVA": "코르테바", "DOW": "다우", "NUE": "뉴코어", "MLM": "마틴마리에타",
            "VMC": "벌칸머티리얼즈", "DD": "듀폰"}),
        Sector("XLRE", "부동산", "XLRE", "Real Estate Select Sector SPDR", {
            "PLD": "프로로지스", "AMT": "아메리칸타워", "EQIX": "에퀴닉스", "WELL": "웰타워", "SPG": "사이먼프로퍼티",
            "PSA": "퍼블릭스토리지", "O": "리얼티인컴", "CCI": "크라운캐슬", "DLR": "디지털리얼티", "VICI": "VICI",
            "EXR": "엑스트라스페이스", "AVB": "아발론베이"}),
        Sector("XLC", "통신서비스", "XLC", "Communication Services Select Sector SPDR", {
            "META": "메타", "GOOGL": "알파벳", "NFLX": "넷플릭스", "TMUS": "T모바일", "DIS": "디즈니", "VZ": "버라이즌",
            "T": "AT&T", "CMCSA": "컴캐스트", "EA": "일렉트로닉아츠", "TTWO": "테이크투", "CHTR": "차터",
            "WBD": "워너브라더스디스커버리"}),
    ])

KR = Country(
    "KR", "한국", "KRW", "069500.KS", "KOSPI200(KODEX 200)", "153130.KS", False, 5e9, [
        Sector("SEMI", "반도체", "091160.KS", "KODEX 반도체", _kr({
            "005930": "삼성전자", "000660": "SK하이닉스", "042700": "한미반도체", "000990": "DB하이텍",
            "058470.KQ": "리노공업", "240810.KQ": "원익IPS", "403870.KQ": "HPSP", "039030.KQ": "이오테크닉스",
            "357780.KQ": "솔브레인", "095340.KQ": "ISC"})),
        Sector("BATT", "2차전지", "305720.KS", "KODEX 2차전지산업", _kr({
            "373220": "LG에너지솔루션", "006400": "삼성SDI", "051910": "LG화학", "003670": "포스코퓨처엠",
            "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로", "066970": "엘앤에프", "005070": "코스모신소재",
            "096770": "SK이노베이션"})),
        Sector("AUTO", "자동차", "091180.KS", "KODEX 자동차", _kr({
            "005380": "현대차", "000270": "기아", "012330": "현대모비스", "204320": "HL만도",
            "161390": "한국타이어앤테크놀로지", "011210": "현대위아", "307950": "현대오토에버"})),
        Sector("BANK", "은행", "091170.KS", "KODEX 은행", _kr({
            "105560": "KB금융", "055550": "신한지주", "086790": "하나금융지주", "316140": "우리금융지주",
            "138040": "메리츠금융지주", "024110": "기업은행", "175330": "JB금융지주", "138930": "BNK금융지주"})),
        Sector("SEC", "증권", "102970.KS", "KODEX 증권", _kr({
            "006800": "미래에셋증권", "071050": "한국금융지주", "005940": "NH투자증권", "016360": "삼성증권",
            "039490": "키움증권", "003540": "대신증권"})),
        Sector("INS", "보험", "140700.KS", "KODEX 보험", _kr({
            "032830": "삼성생명", "000810": "삼성화재", "005830": "DB손해보험", "001450": "현대해상",
            "088350": "한화생명", "000370": "한화손해보험"})),
        Sector("HEALTH", "헬스케어", "266420.KS", "KODEX 헬스케어", _kr({
            "207940": "삼성바이오로직스", "068270": "셀트리온", "000100": "유한양행", "128940": "한미약품",
            "196170.KQ": "알테오젠", "326030": "SK바이오팜", "302440": "SK바이오사이언스", "145020.KQ": "휴젤",
            "214150.KQ": "클래시스"})),
        Sector("CONST", "건설", "117700.KS", "KODEX 건설", _kr({
            "000720": "현대건설", "028050": "삼성E&A", "375500": "DL이앤씨", "006360": "GS건설",
            "047040": "대우건설", "294870": "HDC현대산업개발"})),
        Sector("HEAVY", "조선·중공업", "139230.KS", "TIGER 200 중공업", _kr({
            "329180": "HD현대중공업", "009540": "HD한국조선해양", "010140": "삼성중공업", "042660": "한화오션",
            "034020": "두산에너빌리티", "012450": "한화에어로스페이스", "064350": "현대로템",
            "267260": "HD현대일렉트릭"})),
        Sector("CHEM", "에너지화학", "117460.KS", "KODEX 에너지화학", _kr({
            "096770": "SK이노베이션", "010950": "S-Oil", "011170": "롯데케미칼", "051910": "LG화학",
            "011780": "금호석유", "009830": "한화솔루션", "078930": "GS"})),
        Sector("STEEL", "철강소재", "117680.KS", "KODEX 철강", _kr({
            "005490": "POSCO홀딩스", "004020": "현대제철", "010130": "고려아연", "103140": "풍산",
            "460860": "동국제강"})),
        Sector("CONS", "경기소비재", "139290.KS", "TIGER 200 경기소비재", _kr({
            "005380": "현대차", "000270": "기아", "035420": "NAVER", "035720": "카카오", "352820": "하이브",
            "139480": "이마트", "023530": "롯데쇼핑", "008770": "호텔신라"})),
        Sector("STAPLE", "생활소비재", "266410.KS", "KODEX 필수소비재", _kr({
            "033780": "KT&G", "090430": "아모레퍼시픽", "051900": "LG생활건강", "097950": "CJ제일제당",
            "271560": "오리온", "004370": "농심", "282330": "BGF리테일"})),
    ])

COUNTRIES = [US, KR]

# 섹터 순환 규칙(결과를 보기 전에 고정): 추세 강도 상위 3개 섹터, 섹터끼리는 대부분 상관이 높아 0.9까지 허용
SECTOR_RULE = {"top_n": 3, "hold_buffer": 1, "corr_max": 0.9, "max_weight": 0.5}
