# -*- coding: utf-8 -*-
"""
윈도우 "휴대폰과 연결"(Phone Link, 구 "당신의 휴대폰") 앱을 pywinauto로 조작한다.

⚠ 중요: 이 파일의 컨트롤 탐색 셀렉터(자동화ID/컨트롤타입/이름)는 실제 화면
스크린샷 한 장으로 레이아웃만 확인하고 작성한 것이라 여전히 추정이 섞여
있다. capture_location_auto.py가 국민신문고 목록/상세 화면의 버튼을 여러
후보로 시도했던 것과 같은 이유 — 정확한 접근성 이름을 실제로 확인 못 했으니,
실제 윈도우 PC에서 아래 순서로 한 번 맞춰봐야 한다.

    1. 휴대폰과 연결 앱을 켜고 메시지 화면을 열어둔다.
    2. python phone_link.py --dump  를 실행한다.
       -> 창의 전체 컨트롤 트리(자동화ID, 컨트롤타입, 이름)가 출력된다.
    3. 그 출력에서 대화 목록 / 메시지 말풍선 / 새 메시지 입력창 / 보내기
       버튼에 해당하는 실제 automation_id 또는 title을 확인해서,
       아래 _CONVERSATION_LIST_CRITERIA / _COMPOSE_BOX_CRITERIA /
       _SEND_BUTTON_CRITERIA 상수를 그 값으로 바꿔준다.

확인된 실제 화면 구성 (스크린샷 기준, 2026-08):
    - 창 제목: "휴대폰과 연결" (그냥 "휴대폰 연결"이 아니라 조사 "과"가 낀다 —
      WINDOW_TITLE_RE가 이걸 놓치면 창을 아예 못 찾는다).
    - 상단 탭: 메시지 / 통화 / 사진.
    - 좌측 "메시지" 패널: 제목 옆에 새 메시지(연필 아이콘) 버튼, 그 아래
      검색창, 그 아래 "최근" 그룹 헤더, 그 아래 대화 목록(각 행 = 발신자
      아바타 + 이름또는번호 + 시각 + 마지막 메시지 미리보기 2줄).
    - 발신자 표시가 전화번호(010-XXXX-XXXX)만 있는 게 아니라 "114" 같은
      단문 발신코드나 이메일 형태 문자열(웹발신/RCS 등)도 섞여 나온다 —
      _PHONE_RE로 전화번호 패턴만 걸러 받는 지금 방식이 정확히 맞다.
    - 우측 대화창: 상단에 상대방 이름, 날짜 구분선("오늘" 등), 메시지
      말풍선들, 맨 아래 "메시지 보내기" placeholder가 있는 입력창 한 줄에
      이모지/GIF/사진 아이콘과 종이비행기 모양 보내기 버튼이 나란히 있다.
      보내기 버튼은 텍스트 라벨이 안 보이는 아이콘 버튼이라 이름으로 못
      찾을 가능성이 높다 — _find_send_button이 입력창과 같은 줄(세로
      위치가 비슷한) 버튼 중 가장 오른쪽 것을 고르는 방식으로 대비한다.

사전 설치 (윈도우 PC에서):
    pip install pywinauto pywin32 requests

사용 예:
    python phone_link.py --dump                              (화면 구조 덤프)
    python phone_link.py --send "010-1234-5678" "안내 문자입니다"  (단발 발송 테스트)
"""
import argparse
import re
import time

# pywinauto는 윈도우 전용(pywin32 의존)이라, 이 모듈을 import하는 것 자체가
# 리눅스/개발 환경에서는 실패한다. app.py의 /api/send 라우트가 이 모듈을
# 함수 안에서 지연 import하는 것도 이 때문 — 그래야 대시보드 서버 자체는
# 어떤 OS에서든 문제없이 뜬다.
from pywinauto.application import Application
from pywinauto import Desktop

# 실행 파일 이름 — 프로세스 기준으로 창을 찾는 게 제목 문자열로 찾는 것보다
# 훨씬 안전하다(아래 WINDOW_TITLE_RE의 실패 사례 참고). 마이크로소프트 공식
# Phone Link 앱의 알려진 실행 파일명.
PROCESS_NAME = "PhoneExperienceHost.exe"

# 앱 창 제목 — 실제 화면에서 확인된 "휴대폰과 연결"(조사 포함)과, 혹시 다른
# 버전/영문 설정에서 나올 수 있는 "휴대폰 연결"/"Phone Link"/"Your Phone"도
# 함께 커버한다. ^...$ 로 양끝을 앵커링해서 "제목 전체가 정확히 이 문구"일
# 때만 매칭한다 — 처음엔 .*(...).* 로 느슨하게 잡았다가, 사용자가 이 요청
# 문구("...휴대폰 연결 앱을 통해서...")를 메모장에 저장해둔 창까지 "휴대폰
# 연결 앱"으로 오인해서 --dump가 메모장 창을 잡아버리는 실제 오작동을
# 확인했다 — 느슨한 부분 일치는 제목에 우연히 같은 단어가 들어간 아무
# 창이나 다 걸려버리므로 위험하다.
WINDOW_TITLE_RE = r"^(휴대폰\S*\s*연결|Phone Link|Your Phone)$"

# ── 아래 3개는 실제 화면에서 --dump 결과를 보고 확정해야 하는 자리표시자 ──
# 대화 목록(왼쪽 패널)의 각 항목. 보통 ListItem/DataItem 컨트롤타입.
_CONVERSATION_LIST_CRITERIA = dict(control_type="List")
# 메시지 입력창(하단 텍스트박스, placeholder "메시지 보내기"). 보통 Edit 컨트롤타입.
_COMPOSE_BOX_CRITERIA = dict(control_type="Edit")
# 보내기 버튼 이름 후보 — 스크린샷상 아이콘만 있고 텍스트가 안 보이지만,
# 접근성(스크린리더)용 이름은 따로 붙어있을 수 있어 일단 시도는 해본다.
# 못 찾으면 _find_send_button의 위치 기반 대체 로직으로 넘어간다.
_SEND_BUTTON_NAME_CANDIDATES = ["보내기", "Send", "전송", "메시지 보내기"]
_NEW_MESSAGE_BUTTON_NAME_CANDIDATES = ["새 메시지", "New message", "새 채팅", "메시지 작성"]


def _connect_main_window(timeout: int = 15):
    """이미 실행 중인 휴대폰과 연결 앱 창에 붙는다. 앱이 안 떠 있으면
    RuntimeError — 자동 실행은 시도하지 않는다(사람이 먼저 로그인/연결 상태를
    확인해두는 게 안전하다는 게 이 프로젝트의 다른 스크립트들과 같은 원칙).

    프로세스 이름(PROCESS_NAME) 기준으로 먼저 찾는다 — 창 제목으로 찾으면
    제목에 우연히 같은 단어가 들어간 다른 창(예: 이 요청 문구를 저장해둔
    메모장)을 잘못 잡을 위험이 있다는 걸 실제로 확인했다. 프로세스 연결이
    실패할 때만(예: 실행 파일명이 버전마다 다를 수 있어서) 제목 정규식으로
    대체 시도한다."""
    try:
        app = Application(backend="uia").connect(path=PROCESS_NAME, timeout=timeout)
        win = app.top_window()
        win.wait("exists enabled visible", timeout=timeout)
        return win
    except Exception as e_proc:
        try:
            win = Desktop(backend="uia").window(title_re=WINDOW_TITLE_RE)
            win.wait("exists enabled visible", timeout=timeout)
            return win
        except Exception as e_title:
            raise RuntimeError(
                "휴대폰과 연결 앱 창을 찾지 못했습니다. 앱이 실행 중이고 휴대폰과 "
                f"연결된 상태인지 확인해주세요. (프로세스 연결 실패: {e_proc!r}, "
                f"제목 검색도 실패: {e_title!r})"
            )


def dump_control_tree(depth: int = None):
    """화면 구조를 그대로 출력한다 — 실제 automation_id/이름을 확인해서
    위의 _CONVERSATION_LIST_CRITERIA 등을 채우기 위한 진단용 함수."""
    win = _connect_main_window()
    win.print_control_identifiers(depth=depth)


def _find_send_button(win, compose_box):
    """보내기 버튼은 스크린샷상 종이비행기 아이콘뿐이라 텍스트 이름으로 못
    찾을 가능성이 높다. 이름 후보를 먼저 시도하고, 실패하면 입력창과 같은
    줄(세로 중심이 비슷한 위치)에 있는 버튼 중 가장 오른쪽 것을 고른다 —
    화면 구성이 [메시지 입력창 ... 이모지 GIF 사진 보내기] 순서로 한 줄에
    나란히 있는 걸 스크린샷으로 확인했다. 세로 위치로 먼저 걸러내는 이유는
    상단 툴바의 '...'/설정 버튼처럼 엉뚱한 버튼을 잘못 고르지 않기 위함."""
    for name in _SEND_BUTTON_NAME_CANDIDATES:
        try:
            btn = win.child_window(title=name, control_type="Button")
            if btn.exists(timeout=1):
                return btn
        except Exception:
            continue

    try:
        box_rect = compose_box.rectangle()
        box_mid_y = (box_rect.top + box_rect.bottom) / 2
        same_row = []
        for btn in win.descendants(control_type="Button"):
            try:
                r = btn.rectangle()
            except Exception:
                continue
            if abs(((r.top + r.bottom) / 2) - box_mid_y) < 40:
                same_row.append(btn)
        if same_row:
            same_row.sort(key=lambda b: b.rectangle().left)
            return same_row[-1]
    except Exception:
        pass

    raise RuntimeError("보내기 버튼을 찾지 못했습니다. --dump로 실제 이름/구조를 확인해주세요.")


def _open_conversation(win, phone_number: str, timeout: int = 10):
    """번호로 기존 대화를 찾아 열거나, 없으면 '새 메시지'로 새 대화를 만든다."""
    try:
        row = win.child_window(title_re=f".*{re.escape(phone_number)}.*", control_type="ListItem")
        if row.exists(timeout=2):
            row.click_input()
            time.sleep(1)
            return
    except Exception:
        pass

    # 기존 대화가 없으면 새 메시지 버튼으로 시작한다.
    for name in _NEW_MESSAGE_BUTTON_NAME_CANDIDATES:
        try:
            btn = win.child_window(title=name, control_type="Button")
            if btn.exists(timeout=1):
                btn.click_input()
                time.sleep(1)
                to_box = win.child_window(control_type="Edit", found_index=0)
                to_box.wait("exists enabled visible", timeout=timeout)
                to_box.click_input()
                to_box.type_keys(phone_number, with_spaces=True)
                time.sleep(1)
                # 번호 입력 후 나오는 연락처 후보를 엔터로 확정 — 화면마다
                # 동작이 다를 수 있어 실패해도 무시하고 계속 진행한다.
                try:
                    to_box.type_keys("{ENTER}")
                except Exception:
                    pass
                return
        except Exception:
            continue
    raise RuntimeError("대화를 열지 못했습니다 (기존 대화도 없고 새 메시지 버튼도 못 찾음).")


def send_message(phone_number: str, body: str):
    """phone_number로 body를 발송한다. 실패하면 예외를 던진다 — 호출하는
    쪽(app.py의 /api/send)에서 그대로 502로 응답한다."""
    phone_number = phone_number.strip()
    body = body.strip()
    if not phone_number or not body:
        raise ValueError("phone_number와 body는 비어있을 수 없습니다")

    win = _connect_main_window()
    win.set_focus()
    _open_conversation(win, phone_number)

    compose = win.child_window(**_COMPOSE_BOX_CRITERIA)
    compose.wait("exists enabled visible", timeout=10)
    compose.click_input()
    compose.type_keys(body, with_spaces=True, with_tabs=False, with_newlines=False)
    time.sleep(0.3)

    send_btn = _find_send_button(win, compose)
    send_btn.click_input()
    time.sleep(0.5)


def watch_new_messages(callback, poll_interval: int = 10, max_conversations: int = 20):
    """대화 목록 상위 max_conversations개를 주기적으로 훑어서, 마지막
    메시지가 바뀐(=새 메시지가 온) 대화를 발견하면 callback(phone_number,
    contact_name, body, msg_time)을 호출한다.

    ⚠ 대화 목록 항목에서 번호/이름/마지막 메시지/시각을 뽑아내는 정확한
    방법은 화면 구조에 따라 달라서, 여기서는 항목의 접근성 이름(전체 텍스트)
    문자열을 그대로 파싱하는 가장 단순한 방식으로 시작한다. 실제 화면에서
    --dump로 확인한 뒤 _parse_conversation_item을 다듬어야 정확해진다."""
    win = _connect_main_window()
    seen = {}  # {대화 식별자: 마지막으로 본 미리보기 텍스트}

    print(f"[감시 시작] {poll_interval}초 간격으로 대화 목록을 확인합니다. 종료: Ctrl+C")
    while True:
        try:
            items = win.descendants(control_type="ListItem")
            for item in items[:max_conversations]:
                try:
                    text = item.window_text() or item.element_info.name
                except Exception:
                    continue
                if not text:
                    continue
                key = text[:40]  # 대화 식별용 — 번호/이름이 앞부분에 오는 경우가 많음
                if seen.get(key) == text:
                    continue  # 마지막으로 본 것과 동일 = 새 메시지 없음
                seen[key] = text
                parsed = _parse_conversation_item(text)
                if parsed:
                    callback(*parsed)
        except Exception as e:
            print(f"[감시] 목록을 읽는 중 오류가 발생해 이번 주기는 건너뜁니다: {e!r}")
        time.sleep(poll_interval)


_PHONE_RE = re.compile(r"01[0-9][-\s]?\d{3,4}[-\s]?\d{4}")


def _parse_conversation_item(text: str):
    """대화 목록 항목의 텍스트에서 (번호, 이름, 마지막메시지, 시각)을 뽑는다.
    형식을 정확히 모르므로 최소한(번호만이라도)만 뽑고, 나머지는 화면에서
    확인한 뒤 다듬는다. 번호를 못 찾으면 None을 돌려줘 이 항목은 건너뛴다."""
    m = _PHONE_RE.search(text)
    if not m:
        return None
    phone = m.group(0)
    return phone, "", text.strip(), ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", action="store_true", help="화면 컨트롤 구조를 출력합니다")
    parser.add_argument("--send", nargs=2, metavar=("PHONE", "BODY"), help="단발 발송 테스트")
    args = parser.parse_args()

    if args.dump:
        dump_control_tree()
    elif args.send:
        send_message(args.send[0], args.send[1])
        print("발송 완료")
    else:
        parser.print_help()
