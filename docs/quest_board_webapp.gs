/**
 * 퀘스트 보드 웹앱(휴대폰·밖에서 보기용, 보기 전용)
 *
 * 집 PC가 매시간 구글 드라이브에 올리는 quest_board.html을 그대로 보여 준다.
 * 배포할 때 '실행 계정: 나', '액세스 권한: 나만'으로 두면 이 구글 계정으로 로그인해야만 열린다.
 * 설치 방법: docs/QUEST_BOARD_WEBAPP.md
 */
const FILE_NAME = 'quest_board.html';

function doGet() {
  const files = DriveApp.getFilesByName(FILE_NAME);
  let latest = null;
  while (files.hasNext()) {
    const f = files.next();
    if (!f.isTrashed() && (!latest || f.getLastUpdated() > latest.getLastUpdated())) latest = f;
  }
  if (!latest) {
    return HtmlService.createHtmlOutput(
      '<p style="font-family:sans-serif;padding:16px">아직 집 PC가 퀘스트 보드를 올리지 않았습니다.<br>' +
      'PC에서 <code>scripts\\run_quest_board.bat</code>을 한 번 실행하거나 다음 정각 5분을 기다려 주세요.<br>' +
      '이 웹앱은 블로거 자동화(python -m blogger_autopost auth)로 로그인한 구글 계정에서 만들어야 합니다.</p>')
      .setTitle('퀘스트 보드');
  }
  return HtmlService.createHtmlOutput(latest.getBlob().getDataAsString('UTF-8'))
    .setTitle('퀘스트 보드')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}
