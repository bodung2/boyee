"""유아 무료 활동지(워크시트) 자동 제작.

흐름(주 3회, 유아 블로그 '무료 활동지' 글):
1. 설계(Claude, worksheet-design 스킬): 주제·연령·영역과 1~2장 구성(spec.json). 원화 보관함에 있는 그림은 다시 쓴다.
2. 원화(library): 없는 그림만 ChatGPT(Codex 그림 생성)로 높은 품질로 새로 그리고 data/worksheets/assets에 모아 계속 쓴다.
3. 그리기(render): 글씨·점선·칸·브랜드 띠는 코드로 그린다(AI 그림에 글씨를 맡기지 않는다). A4 PNG + PDF.
4. 검수(Claude, worksheet-qa 스킬): 완성한 장과 새 원화를 직접 보고 판정. 떨어진 원화는 지우고 다시 그린다.
5. 공유(share): PDF를 블로그 주인 드라이브에 올려 '링크가 있는 사람은 보기' 주소를 만든다.
그 뒤 나눔글은 naver_autopost(--profile worksheet)가 쓰고 검수해 유아 블로그에 올린다.
"""
