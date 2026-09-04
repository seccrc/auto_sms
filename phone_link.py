# -*- coding: utf-8 -*-
"""
윈도우 "휴대폰과 연결"(Phone Link, 구 "당신의 휴대폰") 앱을 pywinauto로 조작한다.

아래 셀렉터는 실제 --dump 결과로 확인된 정확한 automation_id를 쓴다(추측이
아니다). Microsoft가 UWP 컨트롤에 이런 안정적인 auto_id를 붙여두는 덕에
capture_location_auto.py의 국민신문고 화면처럼 "이름이 매번 바뀔 수 있어
여러 후보를 시도"할 필요가 거의 없었다. 다만 버전 업데이트로 auto_id가
바뀔 가능성은 있으니, 뭔가 안 맞으면:

    1. 휴대폰과 연결 앱을 켜고 메시지 화면을 열어둔다(다른 창은 최소화
       — 창 제목 검색이 엉뚱한 창을 잡을 수 있다는 걸 실제로 겪었다).
    2. python phone_link.py --dump  를 실행해서 새 컨트롤 트리를 받는다.
    3. 아래 auto_id 상수들을 갱신한다.

확인된 실제 화면 구성 (--dump 결과 기준, 2026-08):
    - 창 제목: 정확히 "휴대폰과 연결".
    - 좌측 대화 목록: ListBox(auto_id="CVSListView", title="대화"). 그
      바로 아래 GroupBox("섹션 머리글")를 거쳐 각 대화가 ListItem으로
      들어있고, 각 행의 접근성 이름은
      "{발신자}와의 대화 메시지 미리 보기 {마지막 메시지 미리보기}"
      형태다("114와의 대화 메시지 미리 보기 [Web발신]..." 처럼). 발신자
      자리엔 전화번호(010-XXXX-XXXX / +82 10-XXXX-XXXX 둘 다 나옴) 외에
      "114" 같은 단문 발신코드나 이메일 형태 문자열(웹발신/RCS 등), 폰
      주소록에 저장된 연락처 이름("당직실(로드킬)"처럼)도 나온다 — 처음엔
      전화번호 패턴만 걸러 받았는데, 저장된 연락처 이름으로 뜨는 실제
      사람과의 문자까지 같이 걸러져서 놓치는 문제가 있었다. 그래서 지금은
      전화번호 형식 여부와 상관없이 발신자 텍스트를 그대로 받는다 — 다만
      "phone_number"라는 이름의 필드에 전화번호 아닌 값(이름 등)이 들어갈
      수 있다는 뜻이니, 이 값으로 발송(send_message)할 때도 그대로 같은
      문자열을 쓰면(연락처 이름 기준으로 대화를 찾음) 정상 동작한다 —
      실제 화면에서 알림/대화목록 둘 다 같은 표시 이름을 쓰는 걸 확인했다.
    - 새 메시지 버튼: Button(auto_id="NewMessageButton", title="새
      메시지(Ctrl+N)") — 단축키가 title에 붙어있어 정확히 일치하는
      title 문자열로 찾으면 실패하므로 auto_id로 찾는다.
    - 메시지 입력창: Edit(auto_id="InputTextBox") — 주의: 대화 목록
      위쪽의 검색창도 Edit(auto_id="TextBox")라서 그냥
      control_type="Edit"로만 찾으면 둘 중 아무거나 잡힐 수 있다.
    - 보내기 버튼: Button(auto_id="SendMessageButton", title="보내기")
      — 아이콘뿐일 거라 예상했는데 실제로는 접근성 이름이 "보내기"로
      붙어 있었다.
    - 대화창의 개별 메시지: 발신자는 Text(auto_id="MessageSender"),
      본문은 Text(auto_id="MessageBody")로 깔끔하게 분리되어 있다
      (지금은 안 쓰지만, 나중에 대화창을 직접 열어서 읽는 방식으로
      바꾸게 되면 이 auto_id를 쓰면 된다).
    - 홈 화면 좌측 "알림" 패널: Pane(auto_id="NotificationsListScrollHost")
      안에 각 알림이 ListItem으로 들어있다. 실제 문자 알림 하나를 받은
      상태로 --dump해서 확인한 구조:
        ListItem (title="메시지 ⁨010-XXXX-XXXX⁩  {본문}   {날짜시각}")
          Static(auto_id="AppNameTextBlock")            = "메시지"
          Static(auto_id="HoverDateReceivedTextBlock")   = "오후 7:36" 등
          Static(auto_id="CompactModeTitleTextBlock")    = 발신자(번호)
          Static(auto_id 없음, control_type="Text")       = 본문 미리보기
          Edit(auto_id="ReplyTextBox") + Button(auto_id="NotificationReplySend")
      이 패널은 **Wi-Fi 없이 블루투스만으로도 채워지는 걸 실제로 확인
      했다** — CVSListView(대화 목록)의 본문 동기화는 Wi-Fi가 필요해서
      Wi-Fi가 막힌 행정망 PC에서는 watch_new_messages()가 새 메시지를
      못 읽지만, 이 알림 패널 기반 watch_notifications()는 그 상황에서도
      동작한다. 대신 미리보기라 원문이 길면 잘려있을 수 있다.
      AppNameTextBlock이 "메시지"가 아닌 항목(카카오톡 등 다른 앱 알림)은
      걸러서 무시한다.

사전 설치 (윈도우 PC에서):
    pip install pywinauto pywin32 requests

사용 예:
    python phone_link.py --dump                              (화면 구조 덤프)
    python phone_link.py --send "010-1234-5678" "안내 문자입니다"  (단발 발송 테스트)
    python phone_link.py --watch-notifications                (알림 패널 감시 테스트, Ctrl+C로 종료)
    python phone_link.py --restore                            (최소화된 창을 다시 화면으로)

창을 숨기고 싶으면 watch_daemon.py를 --hide 옵션으로 실행하는 걸 권장한다
(첫 폴링을 마친 뒤 자동으로 최소화됨) — 감시를 시작하기 전에 미리
최소화해두면 목록이 계속 안 읽히는 문제가 있어서, 이 파일 자체에는 "지금
바로 최소화"하는 CLI 옵션을 두지 않았다(minimize_window() 함수로는 가능).
"""
import argparse
import re
import time

# pywinauto는 윈도우 전용(pywin32 의존)이라, 이 모듈을 import하는 것 자체가
# 리눅스/개발 환경에서는 실패한다. app.py의 /api/send 라우트가 이 모듈을
# 함수 안에서 지연 import하는 것도 이 때문 — 그래야 대시보드 서버 자체는
# 어떤 OS에서든 문제없이 뜬다.
from pywinauto import findwindows
from pywinauto.application import Application, WindowSpecification
from pywinauto import Desktop

# 실행 파일 이름 — 프로세스 기준으로 창을 찾는 게 제목 문자열로 찾는 것보다
# 훨씬 안전하다(아래 WINDOW_TITLE_RE의 실패 사례 참고). 마이크로소프트 공식
# Phone Link 앱의 알려진 실행 파일명.
PROCESS_NAME = "PhoneExperienceHost.exe"

# 앱 창 제목 — 실제 화면에서 확인된 "휴대폰과 연결"과, 혹시 다른 버전/영문
# 설정에서 나올 수 있는 "휴대폰 연결"/"Phone Link"/"Your Phone"도 함께
# 커버한다. ^...$ 로 양끝을 앵커링해서 "제목 전체가 정확히 이 문구"일 때만
# 매칭한다 — 처음엔 .*(...).* 로 느슨하게 잡았다가, 이 프로젝트 요청 문구를
# 메모장에 저장해둔 창까지 "휴대폰 연결 앱"으로 오인해서 --dump가 메모장
# 창을 잡아버리는 실제 오작동을 확인했다. 느슨한 부분 일치는 제목에 우연히
# 같은 단어가 들어간 아무 창이나 다 걸려버리므로 위험하다.
WINDOW_TITLE_RE = r"^(휴대폰\S*\s*연결|Phone Link|Your Phone)$"

# 실제 --dump로 확인된 automation_id (추측 아님).
_CONVERSATION_LIST_CRITERIA = dict(auto_id="CVSListView", control_type="List")
_COMPOSE_BOX_CRITERIA = dict(auto_id="InputTextBox", control_type="Edit")
_SEND_BUTTON_CRITERIA = dict(auto_id="SendMessageButton", control_type="Button")
_NEW_MESSAGE_BUTTON_CRITERIA = dict(auto_id="NewMessageButton", control_type="Button")
# "새 메시지"의 받는 사람 입력칸 — --dump로 실제 확인해보니 이 Edit의
# auto_id("TextBox")가 좌측 "메시지 검색" 상자의 Edit과 완전히 같아서,
# 창 전체에서 Edit을 찾아 found_index=0으로 집으면(예전 코드) "메시지
# 검색" 쪽이 먼저 걸려버린다 — 그러면 번호를 검색창에 입력하고, 받는
# 사람 칸은 계속 빈 채로 본문만 채워지는 사고로 이어진다(실제 확인됨).
# 그래서 받는 사람 칸을 담고 있는 부모 그룹(ContactSuggestionsBox)
# 안에서만 Edit을 찾아야 한다.
_CONTACT_SUGGESTIONS_BOX_CRITERIA = dict(auto_id="ContactSuggestionsBox", control_type="Group")
_TO_BOX_CRITERIA = dict(auto_id="TextBox", control_type="Edit")

# 대화 목록 행의 접근성 이름 형식: "{발신자}와의 대화 메시지 미리 보기 {미리보기}"
_ROW_PATTERN = re.compile(r"^(.*?)와의 대화 메시지 미리 보기 (.*)$", re.DOTALL)

# 홈 화면 "알림" 패널 컨테이너 — 실제 --dump로 확인된 auto_id.
_NOTIFICATION_LIST_CRITERIA = dict(auto_id="NotificationsListScrollHost")
_NOTIF_APP_NAME_AUTO_ID = "AppNameTextBlock"
_NOTIF_TIME_AUTO_ID = "HoverDateReceivedTextBlock"
_NOTIF_SENDER_AUTO_ID = "CompactModeTitleTextBlock"
_NOTIF_SMS_APP_NAME = "메시지"

# 발신자/시각 필드에 마이크로소프트 UI가 자동으로 끼워넣는 양방향 텍스트
# 제어 문자(U+2066~U+2069 LTR/RTL/FIRST STRONG ISOLATE, POP DIRECTIONAL
# ISOLATE / U+200E,U+200F LTR·RTL MARK) — 화면엔 안 보이지만 window_text()로
# 읽으면 그대로 섞여 나와서(예: "⁨010-2405-3466⁩"), 정규식
# 매칭 전에 제거해야 한다. 리터럴 유니코드 문자 대신 \u이스케이프로 명시해서
# 코드에서 눈으로 봐도 헷갈리지 않게 한다.
_BIDI_STRIP_RE = re.compile(r"[\u2066-\u2069\u200e\u200f]")

# 발신자 칸(CompactModeTitleTextBlock)이 "나"로 뜬 카드에서, 진짜 상대방
# 번호를 본문 후보 줄들 사이에서 되찾을 때 쓰는 패턴 — 줄 전체가 숫자/하이픈/
# 공백(+82 국가번호 표시 포함)뿐이어야 매칭되므로, 답신 본문 문장 중간에
# "062-608-2114"처럼 전화번호가 섞여 있어도 그 문장 전체가 매칭되진 않는다.
_PHONE_LIKE_RE = re.compile(r"^\+?\d[\d\-\s]{6,}\d$")


def _clean_bidi(text: str) -> str:
    return _BIDI_STRIP_RE.sub("", text or "").strip()


def _new_lines_since(prev_lines: list, current_lines: list) -> list:
    """알림 카드는 같은 상대와 문자를 주고받을수록 "A" -> "A B" -> "A B C"
    처럼 뒤에 새 줄이 계속 이어붙는 방식이다(watch_notifications() 설명
    참고). 그래서 지난 폴링 때 본 줄 목록(prev_lines)이 지금 목록
    (current_lines)의 앞부분과 그대로 이어진다면, 그 뒤에 붙은 부분만
    새로 온 줄이다.

    이렇게 "내용"이 아니라 "쌓인 위치"로 새 줄을 가려내면, 완전히 같은
    문구를 짧은 간격으로 여러 번 보내도(예: 테스트 문자를 연달아 보냄)
    매번 정확히 새 줄로 잡힌다 — 이전에는 "이미 본 문구"로 착각해
    건너뛰는 문제가 있었다.

    카드가 "모든 알림 지우기" 등으로 초기화되거나 오래돼서 앞부분 줄이
    밀려나가면, prev_lines가 더 이상 current_lines의 앞부분과 안 맞는다
    — 이 경우엔 prev_lines에 없던 줄만 새 줄로 본다(위치 비교가
    깨졌다고 전부 다시 새 걸로 취급하면, 카드가 리셋된 뒤 예전에 이미
    처리했던 옛날 줄까지 재전송하는 사고로 이어지기 때문에 안전하게
    내용 기준으로 되돌아간다)."""
    if current_lines[:len(prev_lines)] == prev_lines:
        return current_lines[len(prev_lines):]
    prev_set = set(prev_lines)
    return [line for line in current_lines if line not in prev_set]


def _top_window_any_state(app, timeout: int):
    """app.top_window()와 하는 일은 같지만(그 프로세스의 최상위 창을 찾음),
    최소화된 창도 찾을 수 있다.

    실제로 겪은 문제: app.top_window()는 내부적으로
    findwindows.find_elements(process=..., ...)를 visible_only=True(기본값)로
    호출하는데, pywinauto의 uia 백엔드에서 "visible"은 곧
    `not CurrentIsOffscreen`이다 — 그런데 최소화된 창은 UI Automation
    관점에서 IsOffscreen=True로 취급돼서, 최소화 상태에서 감시를 시작하면
    top_window()가 "No windows for that process could be found"로
    실패한다(창이 없는 게 아니라 검색 조건에서 걸러진 것). 그래서 여기서는
    visible_only=False로 직접 검색한다."""
    deadline = time.time() + timeout
    windows = []
    while True:
        windows = findwindows.find_elements(process=app.process, backend="uia", visible_only=False)
        if windows or time.time() >= deadline:
            break
        time.sleep(0.5)
    if not windows:
        raise RuntimeError("No windows for that process could be found")
    criteria = {"backend": "uia"}
    if windows[0].handle:
        criteria["handle"] = windows[0].handle
    else:
        criteria["title"] = windows[0].name
    return WindowSpecification(criteria)


def _connect_main_window(timeout: int = 15):
    """이미 실행 중인 휴대폰과 연결 앱 창에 붙는다. 앱이 안 떠 있으면
    RuntimeError — 자동 실행은 시도하지 않는다(사람이 먼저 로그인/연결 상태를
    확인해두는 게 안전하다는 게 이 프로젝트의 다른 스크립트들과 같은 원칙).

    프로세스 이름(PROCESS_NAME) 기준으로 먼저 찾는다 — 창 제목으로 찾으면
    제목에 우연히 같은 단어가 들어간 다른 창(예: 이 요청 문구를 저장해둔
    메모장)을 잘못 잡을 위험이 있다는 걸 실제로 확인했다. 프로세스 연결이
    실패할 때만(예: 실행 파일명이 버전마다 다를 수 있어서) 제목 정규식으로
    대체 시도한다.

    두 경로 모두 visible_only=False로 찾고, wait()에서도 "visible" 조건은
    빼서 "exists enabled"만 확인한다 — 앱이 최소화된 채로(작업 표시줄에만
    있는 채로) watch_daemon.py를 시작해도 연결에 성공하게 하기 위함
    (_top_window_any_state() 설명 참고). 이후 실제로 목록을 읽으려면
    _restore_if_minimized()로 창을 복원해야 한다."""
    try:
        app = Application(backend="uia").connect(path=PROCESS_NAME, timeout=timeout)
        win = _top_window_any_state(app, timeout)
        win.wait("exists enabled", timeout=timeout)
        return win
    except Exception as e_proc:
        try:
            win = Desktop(backend="uia").window(title_re=WINDOW_TITLE_RE, visible_only=False)
            win.wait("exists enabled", timeout=timeout)
            return win
        except Exception as e_title:
            raise RuntimeError(
                "휴대폰과 연결 앱 창을 찾지 못했습니다. 앱이 실행 중이고 휴대폰과 "
                f"연결된 상태인지 확인해주세요. (프로세스 연결 실패: {e_proc!r}, "
                f"제목 검색도 실패: {e_title!r})"
            )


def dump_control_tree(depth: int = None):
    """화면 구조를 그대로 출력한다 — automation_id가 앱 업데이트로 바뀌었을 때
    다시 확인하기 위한 진단용 함수."""
    win = _connect_main_window()
    win.print_control_identifiers(depth=depth)


def _is_minimized(win) -> bool:
    """창이 지금 최소화된 상태인지 확인한다."""
    import win32gui

    return bool(win32gui.IsIconic(win.handle))


def _restore_if_minimized(win):
    """창이 최소화된 상태면 원래 크기로 되돌린다.

    실제로 확인해보니, 창이 "처음부터" 최소화된 상태로 감시를 시작하면
    알림 목록처럼 화면에 보이는 항목만 UI 요소를 만드는(가상화된)
    컨트롤이 아예 렌더링되지 않아서 계속 빈 목록만 보인다. 반대로 한 번
    정상 크기로 목록을 읽어 가상화된 요소들이 "예열"되고 나면, 그 다음엔
    최소화해도 계속 정상적으로 감지되는 것도 확인했다. 그래서 감시
    루프는 시작하기 직전에 항상 이 함수로 복원부터 해야 안전하다."""
    import win32con
    import win32gui

    if _is_minimized(win):
        win32gui.ShowWindow(win.handle, win32con.SW_RESTORE)


def minimize_window(win=None):
    """휴대폰과 연결 창을 지금 바로 최소화한다. win을 안 주면 새로 연결한다.

    ⚠ 감시를 시작하기 "전에" 이걸 먼저 호출하면 안 된다 — 위
    _restore_if_minimized()의 설명대로, 최소화된 채로 감시가 시작되면
    목록이 계속 안 읽힌다. 감시 루프가 최소 한 번 목록을 읽은 뒤에
    자동으로 호출되도록 watch_notifications()/watch_new_messages()의
    hide_after_start=True 옵션을 쓰는 게 안전하다. 이 함수는 감시가 이미
    한동안 잘 돌고 있는 상태에서 수동으로 즉시 최소화하고 싶을 때 쓰는
    용도다."""
    import win32con
    import win32gui

    if win is None:
        win = _connect_main_window()
    win32gui.ShowWindow(win.handle, win32con.SW_MINIMIZE)


def restore_window():
    """minimize_window()(또는 다른 방식)로 최소화된 창을 다시 화면으로
    복원한다."""
    win = _connect_main_window()
    _restore_if_minimized(win)


def _reconnect_after_failure(win, keep_hidden: bool = False):
    """목록을 읽다가 실패했을 때, 다음 주기를 위해 연결을 새로 시도해서
    win 참조를 갱신한다.

    실제로 겪은 문제: 창을 최소화한 직후부터
    COMError(-2147220991, ...)("이벤트에서 가입자를 불러낼 수 없습니다",
    실제로는 UI Automation의 UIA_E_ELEMENTNOTAVAILABLE)가 매 주기 계속
    반복됐다 — 최소화하기 전에 얻어둔 win/notif_list 참조가 최소화
    이후로 무효화된 채 남아있어서, 죽은 참조로 계속 다시 읽으려다 매번
    똑같이 실패한 것으로 보인다. 실패할 때마다(또는 방금 막 최소화한
    직후에) 이 함수로 참조를 새로 갱신해두면, _connect_main_window()가
    이제 visible_only=False로 찾으므로 창이 최소화된 상태여도 정상적인
    새 참조를 얻을 수 있다. 재연결마저 실패하면 기존 win을 그대로
    돌려줘서 다음 주기에 다시 시도하게 한다.

    keep_hidden=False(기본)면 재연결한 창이 최소화돼 있을 경우 복원한다
    — 아직 한 번도 성공적으로 목록을 읽어 "예열"하지 못한 상태에서
    재연결이 최소화된 창에 걸리면, 복원하지 않는 한 이후 폴링도 계속
    빈 목록만 (에러 없이 조용히) 반환하는 문제가 있었다. keep_hidden=True는
    이미 한 번 예열에 성공해서 의도적으로 숨겨둔 뒤의 재연결에 쓴다 —
    이 경우엔 복원하면 안 된다(숨김 목적 자체가 깨짐)."""
    try:
        new_win = _connect_main_window()
        if not keep_hidden:
            _restore_if_minimized(new_win)
        return new_win
    except Exception as e:
        print(f"[감시] 재연결 실패, 다음 주기에 다시 시도합니다: {e!r}")
        return win


def _phone_variants(phone_number: str) -> list:
    """같은 번호라도 화면엔 010-XXXX-XXXX 또는 +82 10-XXXX-XXXX 두 형식
    중 하나로 대화가 저장돼 있을 수 있어서, 기존 대화를 찾을 때 두 형식을
    다 시도한다. 완벽한 정규화는 아니고(하이픈 유무 등 자잘한 표기 차이는
    남아있음) 국내 010 번호에 한해 흔한 두 형식만 커버한다."""
    digits = re.sub(r"\D", "", phone_number)
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    variants = [phone_number]
    if digits.startswith("010") and len(digits) == 11:
        plain = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        intl = f"+82 10-{digits[3:7]}-{digits[7:]}"
        variants += [plain, intl]
    return list(dict.fromkeys(variants))


def _open_conversation(win, phone_number: str, timeout: int = 10):
    """번호로 기존 대화를 찾아 열거나, 없으면 '새 메시지'로 새 대화를 만든다.
    대화 목록 행의 접근성 이름이 "{번호}와의 대화 메시지 미리 보기 ..."로
    시작하므로, 그 접두어로 정확히 매칭해서 다른 대화의 미리보기 텍스트
    안에 우연히 같은 숫자가 들어있어도 잘못 걸리지 않게 한다.

    ⚠ 실제 행의 접근성 이름은 번호 앞뒤에 눈에 안 보이는 양방향 텍스트
    제어문자(bidi, 예: "⁨010-2405-3466⁩")가 붙어있다(_clean_bidi()가
    있는 이유와 동일). pywinauto의 title_re는 이 원본 텍스트에 그대로
    매칭을 시도하므로, 정리 없이 "^번호..."로 앞에서부터 매칭하면
    항상 실패한다 — 그러면 이미 대화가 있는 번호인데도 매번 "새 메시지"로
    새로 시작하게 되는데, 그 경로가 번호 입력 확정이 불안정해서 실제로
    받는 사람이 빈 채로 본문만 채워지는 사고로 이어진 적이 있다
    (send_message() 설명 참고). 그래서 title_re에 맡기지 않고, 각 행을
    직접 훑어 _clean_bidi()로 정리한 텍스트로 비교한다."""
    conv_list = win.child_window(**_CONVERSATION_LIST_CRITERIA)
    variants = _phone_variants(phone_number)
    try:
        rows = conv_list.descendants(control_type="ListItem")
    except Exception:
        rows = []
    for row in rows:
        try:
            title = _clean_bidi(row.window_text() or row.element_info.name)
        except Exception:
            continue
        if any(title.startswith(f"{v}와의 대화 메시지 미리 보기") for v in variants):
            # 클릭 한 번으로 항상 바로 열리는 게 아니다 — 실제로 클릭이 씹히거나
            # (포커스가 없던 창이라 첫 클릭이 창 활성화로만 소비되는 경우 등)
            # 대화창 렌더링이 느려서, 클릭하고 1초만 무조건 쉰 뒤 "열렸겠지"
            # 하고 그냥 넘어가면 실제로는 화면이 "새 대화를 시작하거나 회신할
            # 대화를 하나 선택하세요"라는 빈 상태 그대로인 채 send_message()로
            # 넘어가서, 입력창(compose)을 못 찾고 10초 뒤 TimeoutError로
            # 실패하는 사고로 이어진다(실제로 재현됨) — 그것도 "왜" 실패했는지
            # 알 수 없는 채로. 그래서 클릭 후 입력창이 실제로 나타났는지 확인하고,
            # 안 나타났으면 한 번 더 클릭해서 재시도하며, 그래도 안 열리면 여기서
            # 바로 구체적인 이유가 담긴 예외를 던진다.
            for attempt in range(2):
                row.click_input()
                try:
                    win.child_window(**_COMPOSE_BOX_CRITERIA).wait(
                        "exists enabled visible", timeout=3 if attempt == 0 else timeout
                    )
                    return
                except Exception:
                    continue
            raise RuntimeError(
                f"{phone_number}와의 기존 대화를 목록에서 찾아 클릭했지만 대화창이 "
                "열리지 않았습니다(입력창이 나타나지 않음) — 휴대폰과 연결 앱이 "
                "느리게 반응했거나 클릭이 씹혔을 수 있습니다. 다시 시도해주세요."
            )

    # 기존 대화가 없으면 새 메시지 버튼으로 시작한다.
    btn = win.child_window(**_NEW_MESSAGE_BUTTON_CRITERIA)
    btn.wait("exists enabled visible", timeout=timeout)
    btn.click_input()
    time.sleep(1)
    # ⚠ 받는 사람 칸은 반드시 ContactSuggestionsBox 그룹 "안에서" 찾아야
    # 한다 — _TO_BOX_CRITERIA 설명 참고. 창 전체에서 찾으면 "메시지 검색"
    # 상자를 잘못 집는다.
    to_box = win.child_window(**_CONTACT_SUGGESTIONS_BOX_CRITERIA).child_window(**_TO_BOX_CRITERIA)
    to_box.wait("exists enabled visible", timeout=timeout)

    # 번호 입력 후 나오는 연락처 후보를 엔터로 확정해야 하는데, 화면마다
    # 동작이 다를 수 있어 실패할 수 있다 — 그래서 입력 후 실제로 그 칸에
    # 뭔가 채워졌는지(placeholder "받는 사람"이 아니라 실제 값으로
    # 바뀌었는지) 확인하고, 안 됐으면 한 번 더 시도한다. 그래도 안 되면
    # "받는 사람"이 빈 채로 본문만 입력되고 조용히 발송 시도하는 사고로
    # 이어지므로, 여기서 예외를 던져 발송 자체를 멈춘다.
    for attempt in range(2):
        to_box.click_input()
        to_box.type_keys(phone_number, with_spaces=True)
        time.sleep(1)
        try:
            to_box.type_keys("{ENTER}")
        except Exception:
            pass
        time.sleep(0.5)
        try:
            filled = bool(_clean_bidi(to_box.window_text()))
        except Exception:
            filled = False
        if filled:
            return

    raise RuntimeError(
        f"받는 사람 칸에 번호({phone_number})가 제대로 입력되지 않았습니다 — "
        "새 대화 시작이 실패한 것으로 보입니다."
    )


def send_message(phone_number: str, body: str):
    """phone_number로 body를 발송한다. 실패하면 예외를 던진다 — 호출하는
    쪽(app.py의 /api/send)에서 그대로 502로 응답한다.

    발송은 click_input()/type_keys()로 실제 마우스/키보드 입력을 흉내내는
    방식이라, 감시(읽기)와 달리 창이 화면에 실제로 보이는 상태여야 한다
    — 최소화된 채로는 안 되는 걸 실제로 확인했다. 그래서 창이 지금
    최소화돼 있으면 발송 직전에 복원하고, 발송이 끝나면(성공하든
    실패하든) 원래 최소화돼 있던 상태 그대로 다시 최소화해서, 대시보드에서
    발송 버튼 한 번 눌렀다고 숨겨둔 창이 계속 화면에 남아있지 않게 한다."""
    phone_number = phone_number.strip()
    body = body.strip()
    if not phone_number or not body:
        raise ValueError("phone_number와 body는 비어있을 수 없습니다")

    win = _connect_main_window()
    was_minimized = _is_minimized(win)
    if was_minimized:
        _restore_if_minimized(win)
    try:
        win.set_focus()
        _open_conversation(win, phone_number)

        compose = win.child_window(**_COMPOSE_BOX_CRITERIA)
        compose.wait("exists enabled visible", timeout=10)
        compose.click_input()
        compose.type_keys(body, with_spaces=True, with_tabs=False, with_newlines=False)
        time.sleep(0.3)

        send_btn = win.child_window(**_SEND_BUTTON_CRITERIA)
        send_btn.wait("exists enabled visible", timeout=10)
        send_btn.click_input()
        time.sleep(0.5)
    finally:
        if was_minimized:
            minimize_window(win)


def _call_on_poll(on_poll, polled_ok: bool):
    """감시 루프가 매 주기 끝에 부르는 훅. 감시 자체가 이것 때문에 멈추면
    안 되므로 예외는 로그만 남기고 삼킨다."""
    if on_poll is None:
        return
    try:
        on_poll(polled_ok)
    except Exception as e:
        print(f"[감시] on_poll 훅에서 오류가 났지만 감시는 계속합니다: {e!r}")


def watch_new_messages(callback, poll_interval: int = 5, max_conversations: int = 20,
                        hide_after_start: bool = False, seen_bodies_by_phone: dict = None,
                        on_poll=None):
    """대화 목록 상위 max_conversations개를 주기적으로 훑어서, 마지막
    메시지 미리보기가 바뀐(=새 메시지가 온) 대화를 발견하면
    callback(phone_number, contact_name, body, msg_time)을 호출한다.

    대화 목록(CVSListView) 안의 ListItem만 훑는다 — 창 전체를 훑으면 지금
    열려있는 대화창의 개별 메시지 ListItem까지 섞여 들어온다(둘 다
    control_type="ListItem"이라 컨테이너로 구분해야 함).

    이 화면은 대화당 "가장 최근 미리보기" 딱 하나만 보여주는 구조라(알림
    카드처럼 여러 줄이 누적되지 않음), 발신자별로 지금까지 본 미리보기
    이력을 순서대로 기억해뒀다가, 마지막으로 본 것과 다르면 새 문자로
    본다. 완전히 똑같은 문구가 바로 다음 미리보기로 또 온 경우는 이
    화면만으로는 구분할 방법이 없다는 한계가 있다(알림 패널 쪽
    watch_notifications()는 줄이 계속 쌓이는 구조라 이 한계가 없음).

    hide_after_start=True면 첫 폴링(목록을 한 번 읽어 가상화된 요소를
    "예열"하는 시점)이 끝난 직후 창을 자동으로 최소화한다 — 자세한 이유는
    _restore_if_minimized()/minimize_window() 참고."""
    win = _connect_main_window()
    _restore_if_minimized(win)  # 처음부터 최소화된 채로 시작하면 목록이 안 읽힘
    if seen_bodies_by_phone is None:
        seen_bodies_by_phone = {}  # {발신자: [지금까지 콜백으로 넘긴 미리보기, ...]}
    hidden_already = not hide_after_start

    print(f"[감시 시작] {poll_interval}초 간격으로 대화 목록을 확인합니다. 종료: Ctrl+C")
    while True:
        polled_ok = False
        try:
            conv_list = win.child_window(**_CONVERSATION_LIST_CRITERIA)
            items = conv_list.descendants(control_type="ListItem")
            for item in items[:max_conversations]:
                try:
                    text = item.window_text() or item.element_info.name
                except Exception:
                    continue
                if not text:
                    continue
                parsed = _parse_conversation_item(text)
                if not parsed:
                    continue
                phone, contact_name, preview, msg_time = parsed
                if not preview:
                    continue
                history = seen_bodies_by_phone.setdefault(phone, [])
                if history and history[-1] == preview:
                    continue  # 마지막으로 본 미리보기와 같음 — 아직 그대로인 걸로 봄
                history.append(preview)
                callback(phone, contact_name, preview, msg_time)
            polled_ok = True
        except Exception as e:
            print(f"[감시] 목록을 읽는 중 오류가 발생해 이번 주기는 건너뜁니다: {e!r}")
            win = _reconnect_after_failure(win, keep_hidden=hidden_already)
        if polled_ok and not hidden_already:
            minimize_window(win)
            hidden_already = True
            win = _reconnect_after_failure(win, keep_hidden=True)  # 최소화 직후 이전 참조가 무효화될 수 있어 미리 갱신
            print("[숨김] 첫 폴링을 마쳐 창을 최소화했습니다.")
        _call_on_poll(on_poll, polled_ok)
        time.sleep(poll_interval)


def watch_notifications(callback, poll_interval: int = 5, max_items: int = 30,
                         hide_after_start: bool = False, seen_lines_by_sender: dict = None,
                         on_poll=None):
    """홈 화면 "알림" 패널(NotificationsListScrollHost)을 주기적으로 훑어서
    새 문자 알림을 발견하면 (그 알림 카드에 새로 쌓인 줄마다 한 번씩)
    callback(phone_number, contact_name, body, msg_time)을 호출한다.

    watch_new_messages()(대화 목록 CVSListView 기반)와 달리 이 패널은
    Wi-Fi 없이 블루투스만으로도 채워지는 걸 실제로 확인했다 — 행정망처럼
    PC에 Wi-Fi를 못 붙이는 환경에서는 이쪽을 써야 새 문자를 감지할 수 있다.
    대신 본문이 미리보기라 원문이 길면 잘려있을 수 있다는 한계가 있다.

    같은 상대와 문자를 주고받을수록 알림 카드 하나가 "A" -> "A B" ->
    "A B C"처럼 계속 누적되는 걸 실제로 확인했다(줄마다 별도 Text
    컨트롤로 쌓임). 그래서 "마지막 줄만" 보는 대신, 발신자별로 지금까지
    본 줄 내용을 전부 기억해뒀다가 매 폴링마다 "아직 못 본 줄"만 전부
    콜백으로 넘긴다 — 한 폴링 주기 사이에 같은 상대에게서 문자가 여러 개
    와도(카드에 여러 줄이 한꺼번에 새로 쌓여도) 폴링 간격과 무관하게 전부
    잡힌다.

    "본 줄"은 내용이 아니라 "카드 안에서 몇 번째 줄까지 봤는지"로
    기억한다(_new_lines_since() 참고) — 매 폴링마다 지금 카드의 전체 줄
    목록이 지난번에 기억해둔 목록 뒤에 그대로 이어붙었는지 보고, 이어붙은
    부분만 새 줄로 콜백에 넘긴다. 이렇게 위치로 판단하면 완전히 같은
    문구를 짧은 간격으로 여러 번 보내도(예: 테스트 문자를 연달아 보냄)
    매번 정확히 새 줄로 잡힌다 — 예전에 줄 "내용"만으로 비교했을 때는
    이런 경우 두 번째부터 "이미 본 줄"로 착각해 건너뛰는 문제가 있었다.
    화면에 표시되는 "시각" 문자열로 구분해보려 한 적도 있었지만, 그 값이
    상대 시간 형식이면 카드 내용이 그대로인데도 계속 바뀔 수 있어(예:
    "지금" -> "1분 전") 오히려 같은 카드를 매번 새 걸로 착각하는 정반대
    문제가 생길 위험이 있었다 — 위치 기반 비교는 화면 표시값에 전혀
    의존하지 않아 이 문제도 없다.

    AppNameTextBlock이 "메시지"인 항목만 문자로 취급하고, 카카오톡 등 다른
    앱 알림은 걸러서 무시한다.

    hide_after_start=True면 첫 폴링이 끝난 직후 창을 자동으로 최소화한다.
    실제로 테스트해보니 "시작할 때부터" 최소화돼 있으면 이 목록이 계속
    비어있게 읽히지만, 일단 한 번 정상 크기로 읽고 나면 그 뒤로는
    최소화한 채로도 계속 정상적으로 감지되는 걸 확인했다 — 그래서 시작
    직후 딱 한 번만 "정상 크기로 예열 → 최소화"를 자동으로 해준다.

    seen_lines_by_sender를 넘기면 그 상태로 시작한다({발신자: [지금까지
    콜백으로 넘긴 본문 줄, ...] — 순서 그대로}) — watch_daemon.py를
    재시작해도, 알림 카드에 예전 내용이 그대로 남아있으면 이미 저장된 걸
    "새 줄"로 착각해서 서버로 또 올리는 문제가 있었다. 재시작 전에
    서버에 이미 저장된 내용으로 이 리스트를 미리 채워서 넘기면
    (watch_daemon.py의 _load_recent_seen() 참고), 알림은 그대로 두면서도
    중복 전송을 막을 수 있다. 안 주면 빈 상태로 시작한다(기존 동작과
    동일).

    on_poll(polled_ok)를 넘기면 매 폴링 주기가 끝날 때마다 호출한다 —
    새 문자가 있든 없든 무조건 불리므로, "감시가 살아있다"는 신호를
    서버에 보내는 용도(watch_daemon.py의 heartbeat)로 쓴다. 여기서 나는
    예외는 감시 자체를 멈추지 않도록 삼킨다."""
    win = _connect_main_window()
    _restore_if_minimized(win)  # 처음부터 최소화된 채로 시작하면 목록이 안 읽힘
    if seen_lines_by_sender is None:
        seen_lines_by_sender = {}  # {발신자: [지금까지 콜백으로 넘긴 본문 줄, ...]}
    hidden_already = not hide_after_start

    print(f"[알림 감시 시작] {poll_interval}초 간격으로 알림 패널을 확인합니다. 종료: Ctrl+C")
    while True:
        polled_ok = False
        try:
            notif_list = win.child_window(**_NOTIFICATION_LIST_CRITERIA)
            # 알림이 하나도 없으면("새 알림 없음") 이 컨테이너 자체가 트리에
            # 안 생기는 걸 실제로 확인했다 — ElementNotFoundError가 나는 게
            # 정상적인 "알림 없음" 상태이지, 진짜 오류가 아니다. exists()로
            # 먼저 확인해서, 없으면 조용히 빈 목록으로 취급하고 다음 주기로
            # 넘어간다(에러로 취급해 재연결까지 할 필요 없음).
            items = notif_list.descendants(control_type="ListItem") if notif_list.exists(timeout=1) else []
            for item in items[:max_items]:
                parsed = _parse_notification_item(item)
                if not parsed:
                    continue
                phone, contact_name, body_lines, msg_time = parsed
                body_lines = [line for line in body_lines if line]
                prev_lines = seen_lines_by_sender.get(phone, [])
                for line in _new_lines_since(prev_lines, body_lines):
                    callback(phone, contact_name, line, msg_time)
                seen_lines_by_sender[phone] = body_lines
            polled_ok = True
        except Exception as e:
            print(f"[알림 감시] 목록을 읽는 중 오류가 발생해 이번 주기는 건너뜁니다: {e!r}")
            win = _reconnect_after_failure(win, keep_hidden=hidden_already)
        if polled_ok and not hidden_already:
            minimize_window(win)
            hidden_already = True
            win = _reconnect_after_failure(win, keep_hidden=True)  # 최소화 직후 이전 참조가 무효화될 수 있어 미리 갱신
            print("[숨김] 첫 폴링을 마쳐 창을 최소화했습니다.")
        _call_on_poll(on_poll, polled_ok)
        time.sleep(poll_interval)


# 알림 카드 안의 버튼(통화 걸기/읽음으로 표시/보내기 등)에도 접근성 이름이
# control_type="Text"인 하위 라벨이 딸려있어서(예: Button('통화') 안의
# Static('통화')), auto_id 없는 Text를 전부 "본문"으로 잡으면 이 라벨들까지
# 본문에 섞여 들어온다("...안녕하세요~~~ 통화 읽음으로 표시" 처럼 실제로
# 확인됨). 부모가 Button인 Text는 걸러내는 걸 기본으로 하되, 혹시 그 판단이
# 실패하는 경우에 대비해 알려진 버튼 라벨 문자열도 이중으로 걸러낸다.
_NOTIF_BUTTON_LABELS = {"통화", "읽음으로 표시", "보내기", "이모지", "GIF", "이미지 첨부"}
# 알림에서 바로 빠른 회신을 입력하는 동안, 카드가 잠깐 "회신 작성/전송" 상태로
# 바뀌면서 발신자 칸에 상대방 이름 대신 "나"가 뜨는 걸 실제로 확인했다(그때
# 본문 칸엔 아직 조합 중인 IME 글자가 잡혀서 자모가 깨진 채로 들어오기도 함).
# 실제 문자 발신자가 "나"일 수는 없으니, 이런 과도기 상태는 저장하지 않고
# 건너뛴다 — 카드가 원래 상태로 돌아오면 다음 폴링에서 정상적으로 다시 읽힌다.
#
# 같은 카드 "안"에서도 쓰인다: 한 상대와 대화를 주고받은 지 오래돼 카드가
# 길어지면, 중간중간 "나" 또는 "{상대 번호}" 같은 소제목이 다시 등장해서
# "여기부터는 누가 보낸 거다"를 알려주는 걸 실제 화면에서 확인했다(맨 위
# CompactModeTitleTextBlock과 달리 이 소제목들은 auto_id가 없는 평범한
# Text라서, 안 걸러내면 "나"/"010-2405-3466" 같은 줄이 그대로 본문 목록에
# 섞여 들어간다 — 실제로 [저장] 010-2405-3466: 나 / [저장] 010-2405-3466:
# 010-2405-3466 처럼 저장되는 걸 확인했다). _parse_notification_item()에서
# 본문 후보 텍스트가 이 집합에 있거나 이미 확정된 sender와 완전히 같으면
# 소제목으로 보고 건너뛴다.
_NOTIF_SELF_SENDER_LABELS = {"나"}


def _parse_notification_item(item) -> tuple:
    """알림 패널의 ListItem 하나에서 (번호, "", 본문 줄 목록, 시각)을 뽑는다.
    본문이 하나의 문자열이 아니라 "목록"인 이유는 watch_notifications()가
    호출자 쪽에서 어떤 줄이 이미 처리됐는지 판단해야 하기 때문이다 —
    자세한 이유는 watch_notifications()의 설명 참고.

    ⚠ item.child_window(...)를 쓰지 않는다 — 실제로 돌려봤더니
    "'ListItemWrapper' object has no attribute 'child_window'" 에러가 났다.
    상위 컨테이너(List)에서 얻은 요소와 달리, ListItem 하나짜리 래퍼는
    pywinauto에서 child_window()를 지원하지 않는 걸로 보인다 — descendants()는
    되는 걸 이미 상위 호출(win.child_window(...).descendants(...))에서
    확인했으므로, 이 함수도 descendants()로 한 번만 훑어서 auto_id로
    분류하는 방식으로 통일한다.

    문자 알림이 아니면 None. 발신자는 전화번호 형식이 아니어도(폰
    주소록에 저장된 연락처 이름 등) 그대로 받는다 — 처음엔 전화번호
    패턴만 걸러 받았는데, 그러면 저장된 연락처 이름으로 뜨는 실제 사람과의
    문자까지 같이 놓치는 문제가 있어서 뺐다. sender가 비어있거나
    "나"(알림에서 직접 회신을 입력하는 동안 카드가 잠깐 그렇게 표시되는
    과도기 상태 — _NOTIF_SELF_SENDER_LABELS 참고)인 경우만 걸러낸다.

    ⚠ 여기서 나는 예외는 절대 조용히 삼키지 않는다 — 예전에 통째로
    try/except로 감싸서 None을 돌려줬더니, 실제로는 뭔가 실패하고 있는데도
    "감지된 게 없다"처럼 보여서 원인(child_window 문제)을 한참 못 찾았다.
    항목 하나만 건너뛰고 나머지는 계속 처리하되, 그 내용을 출력해서 다음에
    또 이런 문제가 생기면 바로 보이게 한다."""
    try:
        app_name = ""
        sender = ""
        msg_time = ""
        body_lines = []
        # "우리가 보낸 답신 줄"을 화면 구조(카드 안 "나" 소제목 위치)로
        # 추측해서 미리 걸러내던 걸 그만뒀다 — 알림 카드 레이아웃이 대화
        # 길이/버전에 따라 계속 달라져서 이 추측이 여러 번 서로 다른
        # 방식으로 틀렸다(같은 번호로 온 진짜 문자를 놓치는 사고, 반대로
        # 우리 답신을 가짜 수신 문자로 잘못 저장하는 사고가 각각 따로
        # 실제로 발생함). 대신 여기서는 버튼 라벨 등 명백한 UI 잡음만
        # 걸러내고 나머지는 전부 본문 후보로 넘긴다 — "이게 우리가 이미
        # 보낸 문구와 똑같은가"는 app.py의 api_save_message()가 서버 DB
        # 기록(우리가 실제로 보낸 정확한 문구)을 대조해서 판단한다
        # (self_echo). 화면이 어떻게 쌓이든 우리가 뭘 보냈는지는 우리
        # DB가 항상 정확히 알고 있으므로 이쪽이 훨씬 안정적이다.
        # body_line_is_field: body_lines와 나란히 움직이는 목록 — 그 줄의
        # "원본"(bidi 정리 전) 텍스트가 U+2068(FSI)로 시작해 U+2069(PDI)로
        # 끝나는, 즉 윈도우가 전화번호/"나" 같은 "필드성" 값에 씌우는
        # 방향성 격리 표시로 통째로 감싸여 있었는지를 기록한다. 사람이
        # 문자로 실제 입력한 본문은(그 내용이 우연히 숫자로만 이루어진
        # 전화번호처럼 보이더라도) 이렇게 감싸이지 않는다 — 아래
        # sender=="나" 복구 로직에서 "본문 사이에 다시 나온 진짜 상대방
        # 번호 소제목"과 "상대방이 실제로 전화번호를 문자로 보낸 경우"를
        # 구분하는 데 쓴다.
        body_line_is_field = []
        for text_el in item.descendants(control_type="Text"):
            try:
                auto_id = text_el.element_info.automation_id
            except Exception:
                auto_id = None
            raw = text_el.window_text() or ""
            txt = _clean_bidi(raw)
            if auto_id == _NOTIF_APP_NAME_AUTO_ID:
                app_name = txt
            elif auto_id == _NOTIF_SENDER_AUTO_ID:
                sender = txt
            elif auto_id == _NOTIF_TIME_AUTO_ID:
                msg_time = txt
            elif txt:
                raw_stripped = raw.strip()
                is_field_value = raw_stripped.startswith("\u2068") and raw_stripped.endswith("\u2069")
                if txt in _NOTIF_SELF_SENDER_LABELS:
                    continue  # "나" 소제목 자체는 UI 구간 표시일 뿐, 실제 문자 내용이 아님
                if txt == sender:
                    continue  # 상대방 소제목 재등장 — 본문 아님
                try:
                    parent_type = text_el.parent().element_info.control_type
                except Exception:
                    parent_type = None
                if parent_type == "Button" or txt in _NOTIF_BUTTON_LABELS:
                    continue  # 버튼 라벨(통화/읽음으로 표시 등) — 본문 아님
                body_lines.append(txt)
                body_line_is_field.append(is_field_value)

        if app_name != _NOTIF_SMS_APP_NAME:
            return None  # 문자가 아닌 다른 앱 알림(카카오톡 등)은 건너뜀

        if sender in _NOTIF_SELF_SENDER_LABELS:
            # CompactModeTitleTextBlock이 "나"로 뜨는 건 알림에서 직접 회신을
            # 입력하는 잠깐의 과도기 상태만이 아니었다 — 실제 --dump로
            # 확인해보니, 그 대화에서 우리가 마지막으로 답신을 보낸 뒤로는
            # 상대방이 새 문자를 보내기 전까지 계속 "나"로 떠 있었다. 예전
            # 코드는 이 경우 항목을 통째로 버렸는데(sender를 못 구했으니),
            # 그러면 watch_notifications()가 그 번호의 진행 상태(seen_lines)를
            # 전혀 갱신하지 못한 채로 폴링마다 계속 건너뛰게 되고, 그 사이
            # 실제로 새 문자가 와도 카드가 아직 "나"로 남아있는 동안은 계속
            # 못 잡는 사고로 이어진다(사용자가 "지금 수신이 안 되고 있다"고
            # 보고한 상황과 정확히 일치).
            #
            # 다행히 이 상태에서도 진짜 상대방 번호가 본문 후보 줄들 사이에
            # 소제목처럼 다시 나온다는 걸 같은 dump로 확인했다. 처음엔 이게
            # 항상 맨 끝(답신 입력창 바로 위, 번호+저장된 이름 순서)에만
            # 나온다고 보고 마지막 두 줄만 살펴봤는데, 실제로 그 뒤에 상대가
            # 새 문자를 몇 통 더 보내면(그런데도 CompactModeTitleTextBlock은
            # 계속 "나"로 남아 있었다 — 답신 후 title이 항상 상대 번호로
            # 되돌아온다는 가정 자체가 틀렸다) 번호 소제목 뒤로 진짜 새 문자
            # 줄들이 계속 붙어서, 번호가 더 이상 맨 끝 근처에 있지 않았다.
            # 그래서 위치 제한은 버리고 본문 후보 전체에서 찾는다.
            #
            # ⚠ 상대방이 문자 "내용"으로 진짜 전화번호를 보낼 수도 있어서
            # (예: "제 번호는 010-1234-5678입니다"가 아니라 그냥 번호만
            # 달랑), 단순히 "숫자/하이픈처럼 생겼다"는 것만으로 판단하면 그
            # 진짜 문자를 소제목으로 착각할 위험이 있다. 그래서 원본 텍스트가
            # 윈도우가 전화번호 같은 "필드성" 값에만 씌우는 방향성 격리
            # 표시(U+2068~U+2069)로 감싸여 있었을 때만(body_line_is_field —
            # 사람이 직접 입력한 문자 본문은 이렇게 감싸이지 않는다) 소제목으로
            # 인정한다. 그 줄 하나만 본문에서 빼고(바로 다음 줄이 저장된
            # 이름일 수도, 진짜 새 문자일 수도 있어 구분할 방법이 없으므로
            # 건드리지 않는다 — 최악의 경우 이름 한 줄이 잘못된 수신 문자로
            # 잘못 저장되는 정도이지, 진짜 문자를 지우는 것보다는 훨씬 낫다),
            # 못 찾으면 복구를 포기하고 아래에서 안전하게 건너뛴다.
            #
            # ⚠ 이 소제목은 카드 하나 안에 한 번만 나온다는 보장이 없다 — 긴
            # 대화에서 "나"↔상대 구간이 여러 번 바뀌면 같은 번호 소제목이
            # 여러 줄에 걸쳐 반복해서 나올 수 있다. 예전엔 맨 뒤에서부터
            # 찾은 것 "하나만" 지우고 break했는데, 그러면 앞쪽에 남은 다른
            # 소제목 줄이 그대로 본문으로 저장돼 "010-2405-3466"이라는
            # 문자를 상대가 보낸 것처럼 잘못 기록되는 사고로 이어졌다(실제
            # 확인됨). 그래서 조건에 맞는 줄은 전부 걷어낸다 — 각 줄은
            # bidi 격리 표시(사람이 입력한 본문이면 절대 안 씌워짐) +
            # 전화번호 형태라는 같은 안전 조건을 통과한 것들이라, 여러 개를
            # 지워도 진짜 문자를 지울 위험은 없다.
            recovered = None
            kept_lines, kept_is_field = [], []
            for line, is_field in zip(body_lines, body_line_is_field):
                if is_field and _PHONE_LIKE_RE.match(line):
                    recovered = line
                    continue
                kept_lines.append(line)
                kept_is_field.append(is_field)
            if recovered:
                sender = recovered
                body_lines, body_line_is_field = kept_lines, kept_is_field

        if not sender:
            return None
        if sender in _NOTIF_SELF_SENDER_LABELS:
            return None  # 번호를 되찾지 못했다 — 진짜 회신 입력 중 과도기로 보고 건너뜀

        return sender, "", body_lines, msg_time
    except Exception as e:
        print(f"[알림 감시] 항목 하나를 읽다 오류가 나서 건너뜁니다: {e!r}")
        return None


def _parse_conversation_item(text: str):
    """대화 목록 행의 접근성 이름("{발신자}와의 대화 메시지 미리 보기
    {미리보기}")에서 (번호, 이름, 미리보기, 시각)을 뽑는다. 발신자는
    전화번호 형식이 아니어도(폰 주소록에 저장된 연락처 이름 등) 그대로
    받는다 — watch_notifications()/_parse_notification_item()과 같은
    이유로, 전화번호 패턴만 걸렀을 때 저장된 연락처 이름으로 뜨는 실제
    사람과의 문자까지 같이 놓치는 문제가 있었다."""
    m = _ROW_PATTERN.match(text)
    if not m:
        return None
    sender_raw, preview = m.group(1).strip(), m.group(2).strip()
    if not sender_raw:
        return None
    return sender_raw, "", preview, ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", action="store_true", help="화면 컨트롤 구조를 출력합니다")
    parser.add_argument("--send", nargs=2, metavar=("PHONE", "BODY"), help="단발 발송 테스트")
    parser.add_argument(
        "--watch-notifications", action="store_true",
        help="알림 패널 감시를 터미널에서 바로 테스트합니다 (Wi-Fi 없이도 동작, Ctrl+C로 종료)"
    )
    parser.add_argument(
        "--restore", action="store_true",
        help="최소화된 휴대폰과 연결 창을 다시 화면으로 복원합니다"
    )
    args = parser.parse_args()

    if args.dump:
        dump_control_tree()
    elif args.send:
        send_message(args.send[0], args.send[1])
        print("발송 완료")
    elif args.watch_notifications:
        watch_notifications(lambda phone, name, body, t: print(f"[감지] {phone} ({t}): {body[:60]}"))
    elif args.restore:
        restore_window()
        print("창을 화면 안으로 되돌렸습니다.")
    else:
        parser.print_help()
