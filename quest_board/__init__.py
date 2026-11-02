"""퀘스트 보드: 집 PC의 매일 예약 작업(블로그 발행·SNS·이웃 추천·대시보드 등)이 오늘 어떻게 됐는지 한 화면에.

  python -m quest_board                  output/quest_board.html 만들기
  python -m quest_board --open           만들고 브라우저로 열기(scripts/quest_board.bat 더블클릭과 같음)
  python -m quest_board --notify         만들고 오늘 결과 요약을 텔레그램으로(예약 작업 QuestBoard, 매일 23:40)
  python -m quest_board --text           요약을 화면에만 출력

퀘스트 목록은 scripts/setup_all_schedules.ps1의 $Schedule 표(+ 작업 스케줄러에 직접 등록한 작업)에서 읽으므로
새 예약 작업을 표에 넣으면 보드에도 자동으로 나타난다. 발행 여부는 각 파이프라인이 남기는 기록
(data/published_*.json, output/*/날짜/social_state.json, 로그·잠금 파일)과 작업 스케줄러의 마지막 실행 결과로 판단한다.
"""
